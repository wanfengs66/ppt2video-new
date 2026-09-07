"""
本地模式用户模块：无需登录，固定返回本地用户
"""
from fastapi import Request

# 本地模式：固定返回本地用户，无需登录
LOCAL_USER = {"open_id": "local-user", "name": "本地用户", "avatar_url": ""}


async def get_current_user(request: Request) -> dict:
    """本地模式：直接返回本地用户"""
    return dict(LOCAL_USER)


async def get_optional_user(request: Request) -> dict:
    """本地模式：直接返回本地用户"""
    return dict(LOCAL_USER)
