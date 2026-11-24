"""前端联调接口：一次拿到原型需要的 CH / SC / N / AM / CM。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_visitor
from ..db import get_session
from ..models import Visitor
from . import compat
from .documents import _own

router = APIRouter(prefix="/api/documents", tags=["frontend"])


@router.get("/{doc_id}/play-data")
def play_data(doc_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    """原型直接可用的常量集合；还没有骨架时返回 409。"""
    doc = _own(db, doc_id, visitor)
    data = compat.play_data(db, doc.id)
    if data is None:
        raise HTTPException(status_code=409, detail="这本书还没有解析出章节，先等解析完成")
    data["meta"].update({"status": doc.status, "filename": doc.filename, "pageOffset": doc.page_offset})
    return data
