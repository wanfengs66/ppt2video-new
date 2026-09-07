"""
飞书多维表格同步模块
按 open_id 匹配记录，同步：姓名、累计视频时长（分钟）、首次/最后登录时间

参考使用 tenant_access_token，支持以协作者方式添加到多维表格的机器人。
"""
import os
import time
from datetime import datetime
from typing import Optional

import httpx

from config import settings

# 多维表格标识
BITABLE_APP_TOKEN = settings.FEISHU_BITABLE_TOKEN
BITABLE_TABLE_ID = settings.FEISHU_TABLE_ID
# 多维表格同步的应用凭证（为空则复用主应用）
SYNC_APP_ID = settings.FEISHU_BITABLE_APP_ID or settings.FEISHU_APP_ID
SYNC_APP_SECRET = settings.FEISHU_BITABLE_APP_SECRET or settings.FEISHU_APP_SECRET

_token_cache = {"token": "", "expires_at": 0}


async def _tenant_token() -> str:
    """获取 tenant_access_token（协作者模式的机器人用此鉴权）"""
    global _token_cache
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]
    if not SYNC_APP_SECRET:
        raise RuntimeError("飞书应用密钥未配置")
    async with httpx.AsyncClient() as c:
        r = await c.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": SYNC_APP_ID, "app_secret": SYNC_APP_SECRET},
            timeout=10,
        )
        d = r.json()
        token = d.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"获取 tenant_token 失败: {d.get('msg', '')} (code={d.get('code')})")
        expire = d.get("expire", 7200)
        _token_cache = {"token": token, "expires_at": now + expire}
        return token


async def _bitable(method: str, path: str, data: dict = None) -> dict:
    """调用多维表格 API"""
    token = await _tenant_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/{path}"
    async with httpx.AsyncClient() as c:
        r = await c.request(method, url, headers=headers, json=data, timeout=10)
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Bitable API 错误: {d.get('msg', '')} (code={d.get('code')})")
        return d


async def _search(open_id: str) -> Optional[dict]:
    """按 open_id 查找已有记录（全量列出后内存匹配）"""
    token = await _tenant_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records?page_size=500"
    async with httpx.AsyncClient() as c:
        r = await c.get(url, headers=headers, timeout=10)
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"查询记录列表失败: {d.get('msg', '')}")
        for rec in d.get("data", {}).get("items", []):
            if rec.get("fields", {}).get("飞书open_id") == open_id:
                return rec
    return None


async def _upsert(open_id: str, name: str,
                   last_login_ms: int = None,
                   first_login_ms: int = None,
                   video_duration_min: float = None):
    """创建或更新记录

    Args:
        open_id: 飞书 open_id（唯一标识）
        name: 用户姓名
        last_login_ms: 最后登录毫秒时间戳，None 则用当前时间
        first_login_ms: 首次登录毫秒时间戳，仅新建时写入
        video_duration_min: 累计视频时长（分钟），None 不更新
    """
    if last_login_ms is None:
        last_login_ms = int(time.time() * 1000)

    exist = await _search(open_id)
    if exist:
        fields = {"姓名": name, "最后登录时间": last_login_ms}
        if video_duration_min is not None:
            fields["生成视频时长（分钟）"] = str(video_duration_min)
        await _bitable("PUT", f"records/{exist['record_id']}", {"fields": fields})
    else:
        fields = {
            "姓名": name,
            "飞书open_id": open_id,
            "最后登录时间": last_login_ms,
            "首次登录时间": first_login_ms or int(time.time() * 1000),
        }
        if video_duration_min is not None:
            fields["生成视频时长（分钟）"] = str(video_duration_min)
        await _bitable("POST", "records", {"fields": fields})


# ── 公共 API ──────────────────────────────────────────

async def sync_user_login(open_id: str, name: str):
    """用户登录时同步：姓名 + 最后登录时间 + 首次登录时间（仅新用户）"""
    if not BITABLE_APP_TOKEN or not BITABLE_TABLE_ID:
        return
    try:
        await _upsert(open_id, name)
        print(f"[FeishuSync] 登录 OK: {name}")
    except Exception as e:
        print(f"[FeishuSync] 登录异常: {e}")


async def sync_user_usage(open_id: str, name: str):
    """用户使用系统时记录（保留兼容）"""
    await sync_user_login(open_id, name)


async def sync_video_completed(open_id: str, name: str, duration_minutes: float):
    """
    视频生成完成时同步：累计视频时长（分钟），叠加到已有值。
    """
    if not BITABLE_APP_TOKEN or not BITABLE_TABLE_ID:
        return
    if duration_minutes <= 0:
        return
    try:
        exist = await _search(open_id)
        old_val = 0.0
        if exist:
            raw = exist.get("fields", {}).get("生成视频时长（分钟）")
            try:
                old_val = float(raw) if raw else 0
            except (ValueError, TypeError):
                old_val = 0
        total_min = round(old_val + duration_minutes, 1)
        await _upsert(open_id, name, video_duration_min=total_min)
        print(f"[FeishuSync] 视频时长 +{duration_minutes:.1f}min → 累计 {total_min:.1f}min: {name}")
    except Exception as e:
        print(f"[FeishuSync] 视频时长同步异常: {e}")
