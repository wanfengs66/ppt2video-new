"""
历史记录 API（按用户隔离）
"""
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from utils.database import (
    get_video_history, get_video_record, delete_video_record,
    get_statistics, get_total_count,
)

router = APIRouter()


def _uid(user: dict) -> str:
    """提取用户 open_id"""
    return user.get("open_id", "") if user else ""


@router.get("/api/history")
async def list_history(
    page: int = 1,
    page_size: int = 20,
    status: str = None,
    user: dict = Depends(get_current_user),
):
    """获取当前用户的历史记录"""
    uid = _uid(user)
    offset = (page - 1) * page_size
    items = get_video_history(limit=page_size, offset=offset, status=status, open_id=uid)
    total = get_total_count(status=status, open_id=uid)
    return {"history": items, "total": total, "page": page, "page_size": page_size}


@router.get("/api/history/stats")
async def history_stats(user: dict = Depends(get_current_user)):
    """获取当前用户的统计信息"""
    return get_statistics(open_id=_uid(user))


@router.get("/api/history/{job_id}")
async def get_history_item(job_id: str, user: dict = Depends(get_current_user)):
    """获取单个历史记录"""
    record = get_video_record(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


@router.delete("/api/history/{job_id}")
async def remove_history(job_id: str, user: dict = Depends(get_current_user)):
    """删除历史记录（仅限自己的）"""
    deleted = delete_video_record(job_id, open_id=_uid(user))
    if not deleted:
        raise HTTPException(status_code=404, detail="记录不存在或无权操作")
    return {"message": "删除成功"}
