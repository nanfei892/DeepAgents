"""ORM: 订单、工单、审计事件"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

def new_id() -> str:
    # UUID 避免暴漏自增主键，也方便许多示例生成 ID
    return str(uuid4())

class Order(Base):
    # 订单是只读 Tool 的业务数据；真实项目会来自订单服务而非本地表。
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True)    # 权限过滤的关键字段
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    shipping_status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Ticket(Base):
    # 人工审批/投诉/低置信度的持久化载体。
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    reason: Mapped[str] = mapped_column(Text)
    proposed_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)  # 防重复工单。
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class AuditEvent(Base):
    # 轻量审计表；LangSmith Trace 负责更细的 LLM 调用链。
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())