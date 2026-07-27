"""DeepAgents Supervisor / Worker"""
from urllib.request import Request

from openai import base_url

""" DeepAgents 负责推理和委派；业务权限仍有 Python Tool 强制保证。"""

from contextvars import ContextVar
from dataclasses import dataclass, field

from deepagents import create_deep_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.rag import PolicyRAG
from app.schemas import WorkerResult
from app.tools import create_ticket, query_my_order


@dataclass
class RequestContext:
    """一次 HTTP 请求时受控运行时数据，不暴露给模型。"""
    db: AsyncSession
    user_id: str
    session_id:str
    request_key: str
    rag: PolicyRAG
    citations: list[dict] = field(default_factory=list)    # Tool 调用时收集，供 SSE 展示。
    last_result: WorkerResult | None = None

# ContextVar 在 async 并发请求间隔离；不能使用模块级全局变量保存当前用户。
request_context: ContextVar[RequestContext] = ContextVar("request_context")

def current_context() -> RequestContext:
    # 未绑定上下文就调用 Tool 是编排错误，应立即抛出而不是猜用户身份
    return request_context.get()

@tool
async def search_policy(question: str) -> str:
    """查询退换货、物流等政策。没有来源时不得自行回答。"""
    context = current_context()
    result = context.rag.ask(question)    # 同步 Embedding/Reranker 在后续可放线程池。
    context.last_result = result
    context.citations.extend(result.citations)
    return result.model_dump_json()       # Tool 返回 JSON，方便 Agent 可靠读取字段。

@tool
async def lookup_my_order(order_no: str) -> str:
    """查询当期登录用的订单；不可查询他人订单"""
    context = current_context()
    result = await query_my_order(context.db, context.user_id, order_no)   # user_id 来自认证 Header。
    context.last_result = result
    return result.model_dump_json()

def build_model() -> ChatOpenAI:
    # temperature = 0  让路由/工具 决策更加稳定；timeout 防止一次调用长期占住 SSE。
    return ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0,
        timeout=20
    )

SUPERVISOR_PROMPT = """你是电商客服 Supervisor。
你只能我拍以下专职子 Agent：policy_worker、order_worker、after_sales_worker、ticket_worker。
优先选择最小必要的 Worker；不得编造订单、政策或退款结果。
退款/补偿、投诉、无可靠资料或低置信度必须转人工。最终答复应简洁、中文、事实可追溯。"""

def build_supervisor(checkpointer):
    """
    DeppAgents 原生 Supervisor/Worker 配置。
    Tool 通过 ContextVar 取得当前请求的 DB/user_id；模型看不到内部对象，且订单查询仍在 SQL 层 按user_id 过滤。
    """
    # 每个字 Agent 只能拿到完成职责所需的 Tool，遵循最小权限原则。
    subagents = [
        {"name": "policy_worker", "description": "回答退换货、物流、会员政策；必须给出资料来源。", "system_prompt": "先调用 search_policy；没有依据就转人工。", "tools": [search_policy]},
        {"name": "order_worker", "description": "查询当前用户自己的订单和物流。","system_prompt": "只调用 lookup_my_order，不能猜测订单。", "tools": [lookup_my_order]},
        {"name": "after_sales_worker", "description": "判断退款、补偿、投诉风险。","system_prompt": "退款和投诉必须交由 ticket_worker 转人工。", "tools": []},
        {"name": "ticket_worker", "description": "说明人工接管原因。","system_prompt": "不得承诺退款到账，只说明会由人工审核。", "tools": []}
    ]
    # checkpointer 让 thread_id 对应的 Agent 状态可被 PostgreSQL 持久化。
    return create_deep_agent(
        model=build_model(),
        tools=[search_policy, lookup_my_order],
        system_prompt=SUPERVISOR_PROMPT,
        subagents=subagents,
        checkpointer=checkpointer
    )

"""
`create_deep_agent()` 的核心价值不是“多写几个 Prompt”，而是让 Supervisor 可以把复杂任务通过子 Agent 委派、等待结果再综合。
订单归属、退款审批等硬约束仍必须留在 Python 与数据库层，不能相信模型自觉遵守。
"""
