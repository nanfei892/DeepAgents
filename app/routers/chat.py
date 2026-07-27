"""聊天与用户工单 API"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Ticket
from app.schemas import ChatRequest
from app.security import ensure_safe_input, get_user_id, stable_key

router = APIRouter(prefix="/api", tags=["客服"])

def get_service(request: Request):
    # lifespan 启动时把单例服务放入 app.state，路由只负责取用。
    return request.app.state.customer_service

def get_redis(request: Request) -> Redis:
    return request.app.state.redis

@router.post("/chat")
async def chat(
        body: ChatRequest,
        request: Request,
        user_id: str = Depends(get_user_id),
        db: AsyncSession = Depends(get_db)):
    ensure_safe_input(body.question)   # 先安全预检，后面才可能调用模型。
    redis = get_redis(request)
    # SET NX: 只在 key 不存在时写入，天然适合幂等抢锁。
    lock_key = f"idempotency: {stable_key(user_id, body.session_id, body.idempotency_key)}"
    if not await redis.set(lock_key, "1", ex=300, nx=True):
        raise HTTPException(409, "重复请求，请使用新的 idempotency_key")

    async def event_stream():
        # StreamingResponse 持续消费异步生成器，不需要把所有结果积攒到内存。
        try:
            async for event in get_service(request).run(db, user_id, body.session_id, body.question, body.idempotency_key):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"  # 标准 SSE 帧
        except Exception:
            yield 'data: {"type": "error", "message": "系统暂时不可用，请稍后再试"}\n\n'
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/tickets")
async def my_tickets(user_id: str = Depends(get_user_id), db: AsyncSession = Depends(get_db)):
    # 仍按 user_id 过滤，不能因为 “工单列表” 漏掉数据权限
    tickets = (await db.scalars(select(Ticket).where(Ticket.user_id == user_id).order_by(Ticket.created_at.desc()))).all()
    return [{"id": t.id, "category": t.category, "status": t.status, "reason": t.reason, "human_reply": t.human_reply} for t in tickets]
