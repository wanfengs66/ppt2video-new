"""
历史记录 API（本地单用户模式）
"""
from fastapi import APIRouter, HTTPException

from utils.database import (
    get_video_history, get_video_record, delete_video_record,
    get_statistics, get_total_count,
)

router = APIRouter()


@router.get("/api/history")
async def list_history(page: int = 1, page_size: int = 20, status: str = None):
    """获取历史记录列表"""
    offset = (page - 1) * page_size
    items = get_video_history(limit=page_size, offset=offset, status=status)
    total = get_total_count(status=status)
    return {"history": items, "total": total, "page": page, "page_size": page_size}


@router.get("/api/history/stats")
async def history_stats():
    """获取统计信息"""
    return get_statistics()


@router.get("/api/history/{job_id}")
async def get_history_item(job_id: str):
    """获取单个历史记录"""
    record = get_video_record(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


@router.delete("/api/history/{job_id}")
async def remove_history(job_id: str):
    """删除历史记录"""
    deleted = delete_video_record(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"message": "删除成功"}