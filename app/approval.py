"""LangGraph interrupt / Command(resume)"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class ApprovalState(TypedDict, total=False):
    ticket_id: str
    question: str
    decision: str
    human_reply: str
    final_reply: str

def wait_for_human(state: ApprovalState) -> dict:
    """执行到此处时图持久化暂停；返回后从同一行继续。"""
    # interrupt 返回前 LangGraph 自动保存 checkpoint，并把中断信息交给调用方。
    decision = interrupt({
        "ticket_id": state["ticket_id"],
        "question": state["question"],
        "allowed_decisions": ["approval", "reject", "edit"]
    })
    return {"decision": decision["decision"], "human_reply": decision.get("human_reply", "")}

def compose_final_reply(state: ApprovalState) -> dict:
    # 人工 edit 的文本优先级最高，不能由模型二次改写。
    if state["decision"] == "approve":
        return {"final_reply": "人工客服已批准您的售后申请，后续进度会通过工单同步。"}
    if state["decision"] == "edit":
        return {"final_reply": state["human_reply"]}
    return {"final_reply": "人工客服暂未批准该申请。如需补充材料，请在工单中继续说明。"}

def build_approval_graph(checkpointer):
    # 只有 compile 时传入 checkpointer，interrupt/resume 才能跨进程回复。
    graph = StateGraph(ApprovalState)
    graph.add_node("wait_for_human", wait_for_human)
    graph.add_node("compose_final_reply", compose_final_reply)
    graph.add_edge(START, "wait_for_human")
    graph.add_edge("compose_final_reply", END)
    return graph.compile(checkpointer=checkpointer)

"""
`app/service.py` 已经在创建高风险工单后调用该图；调用会在 `interrupt()` 处暂停并将状态写入 PostgreSQL，它不是异常，也不应在此处等待人工结果。
"""