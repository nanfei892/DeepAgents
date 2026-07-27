from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, Ticket
from app.schemas import WorkerResult

async def query_my_order(db: AsyncSession, user_id: str, order_no: str) -> WorkerResult:
    """订单 Tool：始终包含 user_id 过滤，防止 Agent 越权查看别人的订单。"""
    # WHERE 必须同时包含 order_no 与 user_id；只按订单号查询就是越权漏洞
    order = await db.scalar(select(Order).where(Order.order_no == order_no, Order.user_id == user_id))
    if not order:
        return WorkerResult(answer="未找到属于您的该订单。请确认单号。", confidence=0.95, risk_level="low")
    return WorkerResult(
        answer=f"订单 {order.order_no}: 状态为 {order.status}，物流信息：{order.shipping_status}。",
        confidence = 0.99,
        risk_level = "low"
    )

async def create_ticket(
        db: AsyncSession, *, user_id: str, session_id: str, category: str,
        reason: str, idempotency_key: str, proposed_action: str | None = None) -> Ticket:
    # 同一请求重试时直接复用旧工单，避免用户刷新导致重复人工待办。
    ticket = await db.scalar(select(Ticket).where(Ticket.idempotency_key == idempotency_key))
    if ticket:
        return ticket
    ticket = Ticket(
        user_id=user_id, session_id=session_id, category=category, reason=reason,
        proposed_action=proposed_action,idempotency_key=idempotency_key,
    )
    db.add(ticket)     # 暂存到当前事务
    await db.flush()      # 立即取得 ticket.id，但不在 Tool 内抢先 commit
    return ticket

"""
验证订单权限（后续可改为 pytest）：用户 `u_zhang` 查询 `CS20260003` 必须得到“未找到属于您的该订单”，而不是订单详情。
"""