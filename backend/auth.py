"""
本地单用户模式：无需登录，固定返回本地用户
不依赖任何第三方身份体系，不采集用户标识信息
"""
from fastapi import Request

LOCAL_USER = {"name": "本地用户"}


async def get_current_user(request: Request) -> dict:
    """本地模式：直接返回本地用户"""
    return dict(LOCAL_USER)


async def get_optional_user(request: Request) -> dict:
    """本地模式：直接返回本地用户"""
    return dict(LOCAL_USER)