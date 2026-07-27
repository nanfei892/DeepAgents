"""环境变量"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 必填项没有默认值：漏配时应用应立即失败，不要静默连接错误地址
    database_url: str
    checkpoint_database_url: str
    redis_url: str
    # 本地先允许为空，真正调用模型师 由 LangChain 返回明确鉴权错误
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    admin_api_key: str
    # Chroma 的本地持久化目录；Compose 将它映射到命名卷
    chroma_dir: Path = Path("chroma_db")
    knowledge_base_dir: Path = Path(__file__).parent / "knowledge_base"
    reranker_model: str = "BAAI/bge-reranker-base"
    # extra=ignore 允许 .env 存 LangSmith 等第三方变量而不报错
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# 单例配置，其他模块统一 from app.config import settings
settings = Settings()
