"""Pydantic API / Worker DTO"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

class ChatRequest(BaseModel):
    # Field 同时生成 Swagger 文档和运行时请求校验
    question: str = Field(..., min_length=1, max_length=1000)
    session_id: str = Field(..., min_length=1, max_length=64)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        # min_length 不能拦截全空格字符串，因此再 strip() 一次
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()

class WorkerResult(BaseModel):
    # Supervisor 只消费这个稳定契约，不依赖自然语言猜测 Worker 是否成功
    answer: str
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high"]
    citations: list[dict] = Field(default_factory=list)    # 每个实例独立列表，不能写 []
    action: Literal["answer", "refund_request", "create_ticket"] = "answer"
    handoff_reason: str | None = None

class DecisionRequest(BaseModel):
    # 管理员只能三选一；Pydantic 会拒绝未知的 decision
    decision: Literal["approve", "reject", "edit"]
    human_reply: str | None = Field(default=None, max_length=1000)
