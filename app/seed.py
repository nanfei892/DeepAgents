"""脱敏示例订单"""
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Order

async def seed_orders() -> None:
    """只放脱敏教学数据，绝不写入真实客户信息。"""
    async with SessionLocal() as db:
        # 幂等初始化：容器重启后不会重复插入示例订单
        exists = await db.scalar(select(Order.id).limit(1))
        if exists:
            return
        # 两个用户用于之后验证“只能查询自己的订单”
        db.add_all([
            Order(user_id="u_zhang", order_no="CS20260001", status="paid", amount=199.0, shipping_status="待发货"),
            Order(user_id="u_zhang", order_no="CS20260002", status="shipped", amount=399.0, shipping_status="运输中，预计明天送达"),
            Order(user_id="u_li", order_no="CS20260003", status="completed", amount=89.0, shipping_status="已签收"),
        ])
        await db.commit()
