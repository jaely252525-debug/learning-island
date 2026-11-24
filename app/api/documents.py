"""文档接口：上传 / 状态 / 大纲 / 删除。"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import get_visitor
from ..config import settings
from ..db import get_session
from ..models import Document, DocTask, Feedback, Mark, Node, NodePrereq, Page, Visitor
from ..pipeline.queue import enqueue
from ..schemas import DocumentOut, NodeOut, OutlineOut, StatusOut
from ..storage.files import delete_document_files, save_source
from . import compat

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _own(db: Session, doc_id: str, visitor: Visitor) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.visitor_id != visitor.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


def _doc_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        stage=doc.stage,
        progress=doc.progress,
        pageCount=doc.page_count,
        pageOffset=doc.page_offset,
        hasTextLayer=doc.has_text_layer,
        error=doc.error,
        quality=doc.quality_json,
        createdAt=doc.created_at.isoformat() if doc.created_at else None,
    )


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    visitor: Visitor = Depends(get_visitor),
    db: Session = Depends(get_session),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext.lstrip(".") not in settings.allowed_ext_set:
        raise HTTPException(status_code=415, detail=f"不支持的格式 {ext or '(无扩展名)'}")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_file_mb}MB 上限")

    doc_id = "doc_" + uuid.uuid4().hex[:20]
    doc = Document(
        id=doc_id,
        visitor_id=visitor.id,
        filename=(file.filename or f"upload{ext}")[:255],
        mime=file.content_type or "",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key="",
        status="uploaded",
        stage="queued",
    )
    doc.storage_key = save_source(doc_id, ext, data)
    db.add(doc)
    db.commit()
    enqueue(db, doc_id)
    return _doc_out(doc)


@router.get("/{doc_id}/status", response_model=StatusOut)
def document_status(doc_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    doc = _own(db, doc_id, visitor)
    tasks = db.scalars(select(DocTask).where(DocTask.document_id == doc.id).order_by(DocTask.id)).all()
    return StatusOut(
        id=doc.id,
        status=doc.status,
        stage=doc.stage,
        progress=doc.progress,
        pageCount=doc.page_count,
        pageOffset=doc.page_offset,
        hasTextLayer=doc.has_text_layer,
        error=doc.error,
        quality=doc.quality_json,
        tasks=[
            {
                "id": t.id,
                "stage": t.stage,
                "status": t.status,
                "attempts": t.attempts,
                "error": t.error,
                "resumeFrom": t.resume_from,
            }
            for t in tasks
        ],
    )


def outline_payload(db: Session, doc: Document) -> OutlineOut:
    nodes = db.scalars(select(Node).where(Node.document_id == doc.id).order_by(Node.order_index, Node.id)).all()

    def to_out(n: Node) -> NodeOut:
        children = [to_out(c) for c in nodes if c.parent_id == n.id]
        kids = sorted(children, key=lambda c: c.order)
        extra: dict[str, Any] = {}
        if n.level == "chapter":
            extra = {
                "no": n.order_index,
                "icon": compat.CH_EMOJI[(n.order_index - 1) % len(compat.CH_EMOJI)],
                "name": compat.short_title(n.title),
                "sectionCount": sum(1 for c in kids if c.level == "section"),
                "page": n.page_start,
            }
        elif n.level == "section":
            extra = {
                "no": int(n.path.rsplit(".", 1)[-1]) if (n.path or "").count(".") else None,
                "name": compat.short_title(n.title),
                "page": n.page_start,
            }
        return NodeOut(
            id=n.id,
            parentId=n.parent_id,
            level=n.level,
            title=n.title,
            order=n.order_index,
            pageStart=n.page_start,
            pageEnd=n.page_end,
            status=n.status,
            locked=n.locked,
            prerequisites=list(n.prerequisites or []),
            sources=list(n.sources or []),
            importance=n.importance,
            quality=n.quality,
            children=kids,
            **extra,
        )

    chapters = sorted([to_out(n) for n in nodes if n.level == "chapter" and n.parent_id is None], key=lambda c: c.order)
    stats = {
        "chapters": len(chapters),
        "sections": sum(len(c.children) for c in chapters),
        "knowledge": sum(1 for n in nodes if n.level == "knowledge"),
    }
    return OutlineOut(document=_doc_out(doc), chapters=chapters, stats=stats)


@router.get("/{doc_id}/outline", response_model=OutlineOut)
def document_outline(doc_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    return outline_payload(db, _own(db, doc_id, visitor))


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    doc = _own(db, doc_id, visitor)
    node_ids = [n.id for n in db.scalars(select(Node).where(Node.document_id == doc.id))]
    if node_ids:
        db.execute(delete(NodePrereq).where(NodePrereq.node_id.in_(node_ids)))
        db.execute(delete(Mark).where(Mark.node_id.in_(node_ids)))
        db.execute(delete(Feedback).where(Feedback.target_id.in_(node_ids)))
    db.execute(delete(DocTask).where(DocTask.document_id == doc.id))
    db.execute(delete(Page).where(Page.document_id == doc.id))
    db.execute(delete(Node).where(Node.document_id == doc.id))
    db.execute(delete(Document).where(Document.id == doc.id))
    db.commit()
    delete_document_files(doc.id)
