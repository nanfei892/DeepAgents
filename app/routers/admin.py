"""人工审批与指标 API"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Ticket
from app.schemas import DecisionRequest
from app.security import require_admin

router = APIRouter(prefix="/api/admin", tags=["人工工作台"])

@router.get("/tickets", dependencies=[Depends(require_admin)])
async def pending_tickets(db: AsyncSession = Depends(get_db)):
    # 路由级 dependencies 已完成管理员鉴权，函数内无需重复校验。
    tickets = (await db.scalars(select(Ticket).where(Ticket.status == "pending").order_by(Ticket.created_at))).all()
    return [{"id": t.id, "user_id": t.user_id, "category": t.category, "reason": t.reason, "proposed_action": t.proposed_action} for t in tickets]

@router.post("/tickets/{ticket_id}/decision", dependencies=[Depends(require_admin)])
async def decide(ticket_id: str, body: DecisionRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket or ticket.status != "pending":
        raise HTTPException(404, "待处理工单不存在")
    if body.decision == "edit" and not body.human_reply:
        raise HTTPException(400, "编辑回复时 human_reply 不能为空")
    # 显示映射，避免字符串拼接得到错误状态（如 rejected）
    ticket.status = {"approve": "approved", "reject": "rejected", "edit": "edited"}[body.decision]
    ticket.human_reply = body.human_reply
    ticket.resolved_at = datetime.utcnow()
    # 从 PostgreSQL Checkpoint 恢复 interrupt() 后的一张审批图
    # Command(resume=...) 从同一 thread_id 的 interrupt 行继续执行，而非新建图。
    resumed = await request.app.state.customer_service.approval_graph.ainvoke(
        Command(resume={"decision": body.decision, "human_reply": body.human_reply or ""}),
        config={"configurable": {"thread_id": f"ticket:{ticket_id}"}}
    )
    return {"ticket_id": ticket.id, "status": ticket.status, "human_reply": resumed.get("final_reply", ticket.human_reply)}

@router.get("/metrics", dependencies=[Depends(require_admin)])
async def metrics(db: AsyncSession = Depends(get_db)):
    # 先是按照最小可观测指标；生成可改为按时间窗口聚合 AuditEvent
    total = await db.scalar(select(func.count()).select_from(Ticket)) or 0
    pending = await db.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "pending")) or 0
    return {"ticket_total": total, "pending_ticket_total": pending, "handoff_rate_hint": "将聊天总量写入 AuditEvent 后可计算精确转人工率"}
