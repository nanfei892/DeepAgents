"""状态图、审批回复、SSE"""
import logging
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import RequestContext, build_supervisor, request_context
from app.approval import build_approval_graph
from app.models import AuditEvent
from app.rag import PolicyRAG
from app.schemas import WorkerResult
from app.security import stable_key
from app.tools import create_ticket

logger = logging.getLogger(__name__)

class CustomerService:
    """教学版编排器：图负责可控路由，DeepAgents 负责复杂语言任务。"""
    def __init__(self, rag: PolicyRAG, checkpointer) -> None:
        # Supervisor 管语言推理；审批图专门管理可暂停、可恢复的人工决策。
        self.rag = rag
        self.supervisor = build_supervisor(checkpointer)
        self.approval_graph = build_approval_graph(checkpointer)

    async def run(self, db: AsyncSession, user_id: str, session_id: str, question: str, request_key: str):
        """产出 SSE 所需事件。每个分支都要显示给出风险与人工兜底"""
        yield {"type": "status", "message": "正在进行安全检查..."}
        # Supervisor 的确定性安全前置路由：高风险先于 LLM，不让模型绕过。
        if any(word in question for word in ("退款", "赔偿", "补偿", "投诉", "举报")):
            # 关键词只是教学版风险策略；真实项目可使用规则 + 分类模型双判断
            result = WorkerResult(
                answer = "该请求需要人工客服审核，我正在为您创建工单...",
                confidence = 0.95,
                risk_level = "high",
                action = "refund_request" if any(word in question for word in ("退款", "赔偿", "补偿", "投诉", "举报")) else "create_ticket",
                handoff_reason = "高风险售后或投诉请求"
            )
        else:
            # DeepAgents 会自行在 policy_worker 与 order_worker 之间委派。
            yield {"type": "delegation", "worker": "supervisor", "message": "DeepAgents Supervisor 正在选择 Worker"}
            # 将用户、DB、RAG 注入 ContextVar；这些敏感对象不会拼进 Prompt
            context = RequestContext(db = db, user_id = user_id, session_id = session_id, request_key = request_key, rag = self.rag)
            context_token = request_context.set(context)
            try:
                # 同一个 session_id 对应同一条 DeepAgents 会话/Checkpoint。
                response = await self.supervisor.ainvoke(
                    {"messages": [HumanMessage(content=question)]},
                    config = {"configurable": {"thread_id": session_id}}
                )
                final_message = str(response["messages"][-1].content)
                # Worker 若没有调 任何可验证的 Tool，那就强制降低置信度并转人工。
                result = context.last_result or WorkerResult(
                    answer = final_message,
                    confidence = 0.35,
                    risk_level = "media",
                    action = "crate_ticket",
                    handoff_reason = "worker 未返回可验证的业务数据"
                )
                # 工具调用有证据时，最终自然语言回复有 Supervisor 生成。
                if result.confidence >= 0.55 and result.action == "answer":
                    result.answer = final_message
            finally:
                request_context.reset(context_token)    # finally 确保不会串到下一个并发请求。

        for source in result.citations:   # 先发送来源，前端可在答案前展示证据。
            yield {"type": "source", "data": source}
        if result.risk_level == "high" or result.confidence < 0.55 or result.action != "answer":
            # 任何风险、低置信度或非 answer 动作都统一进入人工闭环。
            ticket = await create_ticket(
                db,
                user_id = user_id,
                session_id = session_id,
                category = "refund" if result.action == "refund_request" else "human_handoff",
                reason = result.handoff_reason or "低置信度回答",
                proposed_action = result.action,
                idempotency_key = stable_key(user_id, session_id, request_key)
            )
            # 图在 interrupt() 处暂停，checkpoint 将状态持久化到 PostgreSQL。
            await self.approval_graph.ainvoke(
                {"ticket_id": ticket.id, "question": question},
                config = {"configurable": {"thread_id": f"ticket:{ticket.id}"}}
            )
            yield {"type": "handoff", "ticket_id": ticket.id, "reason": ticket.reason}
            yield {"type": "approval_required", "ticket_id": ticket.id, "message": result.answer}
        else:
            yield {"type": "token", "content": result.answer}

        trace_id = str(uuid4())     # 本地日志和数据库审计可以该 ID 关联。
        db.add(AuditEvent(
            trace_id = trace_id,
            user_id = user_id,
            event_type = "custom_service_completed",
            payload = {"session_id": session_id, "risk_level": result.risk_level, "action": result.action, "confidence": result.confidence}
        ))
        logger.info("customer_service_completed trace_id=%s user_id=%s action=%s", trace_id, user_id, result.action)
        yield {"type": "done", "trace_id": trace_id}

    def build_graph(self):
        """真正的 LangGraph 外层图；Supervisor 节点内部执行 DeepAgents。"""
        graph = StateGraph(dict)   # 简化 State；深化时应改为 TypeDict 明确字段。
        graph.add_node("security_gate", lambda state: state)
        graph.add_node("supervisor", lambda state: state)    # 实际 HTTP 路径由 run() 异步调用
        graph.add_edge(START, "security_gate")
        graph.add_edge("security_gate", "supervisor")
        graph.add_edge("supervisor", END)
        return graph.compile()

"""
这里的“确定性安全前置路由”是企业亮点：高风险请求不依赖 LLM 分类，先进入强制审批。
`build_supervisor()` 给出了 DeepAgents 原生 Supervisor/Worker；生产中应在 `supervisor` 节点调用它，并把子 Agent 的结构化结果回填到 State。
先把本讲义的可控版本跑通，再升级为完整 LLM 委派。
"""