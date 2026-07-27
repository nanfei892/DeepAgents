"""FastAPI 入口"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis

from app.config import settings
from app.database import init_db
from app.rag import PolicyRAG
from app.seed import seed_orders
from app.service import CustomerService
from app.routers import admin, chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastAPI 在接收第一个请求前运行这里；适合连接外部资源。
    await init_db()
    await seed_orders()
    rag = PolicyRAG()   # 初始化会加载/构建 Chroma，因此不要放到每个请求中。
    rag.initialize()
    # Checkpoint 让 interrupt 后的 Agent 状态落在 PostgreSQL，服务重启也能恢复
    checkpoint_cm = AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url)
    app.state.checkpointer = await checkpoint_cm.__aenter__()
    await app.state.checkpointer.setup()
    app.state.customer_service = CustomerService(rag, app.state.checkpointer)
    app.state.redis = Redis.from_url(settings.redis_url, decode_response = True)
    try:
        yield
    finally:
        await app.state.redis.aclose()    # 优雅关闭连接池，防止容器退出时告警。
        await checkpoint_cm.__aexit__(None, None, None)

app = FastAPI(title="DeepAgents 企业级智能客服", lifespan=lifespan)
app.include_router(chat.router)
app.include_router(admin.router)

@app.get("/health")
async def health():
    return {"status": "ok"}

# 必须在 API 路由后挂载根路径， 否则 /health 与 /api/... 会被静态路由吞掉。
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
