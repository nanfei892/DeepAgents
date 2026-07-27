"""身份、注入检测、幂等"""

import hashlib
import re

from fastapi import Header, HTTPException

from app.config import settings

INJECTION_PATTERNS = [
    # 这是教学版快速拦截，生成还应叠加模型分类、审计和权限隔离
    r"ignore\s+(all\s+)?previous", r"忽略(之前|上面).{0,8}(指令|规则)",
    r"system\s+prompt", r"泄露.{0,8}(提示词|密钥)",
]

def ensure_safe_input(text: str) -> None:
    # 命中后在进入模型前失败，避免恶意 Prompt 影响 Worker 的选择。
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in INJECTION_PATTERNS):
        raise HTTPException(400, "输入包含可能绕过系统规则的指令，请换另一种问法")

async def get_user_id(x_user_id: str = Header(..., alias="X-User-Id")) -> str:
    # Header alias 让 HTTP 使用 X-User-Id，Python 使用下划线变量名
    if not re.fullmatch(r"[a-zA-Z0-9_-]{3, 64}", x_user_id):
        raise HTTPException(400, "X-User-Id 格式不合法")
    return x_user_id

async def require_admin(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> None:
    # 教学项目的 API Key；正式系统改用 JWT/OAuth2 + 角色权限表。
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(403, "管理员密钥无效")

def stable_key(user_id: str, session_id: str, key: str) -> str:
    # 组合租户、会话和客户端请求键后哈希，避免 Redis Key 泄露原始输入。
    return hashlib.sha256(f"{user_id}:{session_id}:{key}".encode()).hexdigest()
