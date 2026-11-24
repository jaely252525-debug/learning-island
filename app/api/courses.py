"""多资料合集接口：一次上传多份资料，生成一份统一大纲与一套汇总内容。"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import get_visitor
from ..config import settings
from ..db import get_session
from ..models import (
    Course,
    CourseSource,
    Document,
    DocTask,
    Feedback,
    Mark,
    Node,
    NodePrereq,
    Page,
    Visitor,
)
from ..pipeline.queue import enqueue
from ..schemas import CourseOut, OutlineOut
from ..storage.files import delete_document_files, save_source
from . import compat
from .documents import outline_payload

router = APIRouter(prefix="/api/courses", tags=["courses"])

MAX_SOURCES = 12


def _own_course(db: Session, course_id: str, visitor: Visitor) -> tuple[Course, Document]:
    course = db.get(Course, course_id)
    if course is None or course.visitor_id != visitor.id:
        raise HTTPException(status_code=404, detail="合集不存在")
    doc = db.get(Document, course.document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="合集汇总文档不存在")
    return course, doc


async def _read_files(files: list[UploadFile]) -> list[tuple[UploadFile, bytes, str]]:
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一份资料")
    if len(files) > MAX_SOURCES:
        raise HTTPException(status_code=400, detail=f"一个合集最多 {MAX_SOURCES} 份资料")
    out: list[tuple[UploadFile, bytes, str]] = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext.lstrip(".") not in settings.allowed_ext_set:
            raise HTTPException(status_code=415, detail=f"不支持的格式 {ext or '(无扩展名)'}")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"空文件：{file.filename}")
        if len(data) > settings.max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{file.filename} 超过 {settings.max_file_mb}MB 上限",
            )
        out.append((file, data, ext))
    return out


def _source_items(db: Session, course: Course) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CourseSource).where(CourseSource.course_id == course.id).order_by(CourseSource.order_index, CourseSource.id)
    ).all()
    items = []
    for row in rows:
        doc = db.get(Document, row.document_id)
        if doc is None:
            continue
        items.append(
            {
                "documentId": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "pageCount": doc.page_count,
                "order": row.order_index,
            }
        )
    return items


def _course_out(db: Session, course: Course, doc: Document) -> CourseOut:
    return CourseOut(
        id=course.id,
        title=course.title,
        documentId=course.document_id,
        status=doc.status if doc else course.status,
        stage=doc.stage if doc else course.stage,
        progress=doc.progress if doc else course.progress,
        pageCount=doc.page_count if doc else 0,
        sourceCount=len(_source_items(db, course)),
        error=doc.error if doc else course.error,
        quality=(doc.quality_json if doc else course.quality_json) or {},
        sources=_source_items(db, course),
        createdAt=course.created_at.isoformat() if course.created_at else None,
    )


def _new_source_doc(course_id: str, visitor: Visitor, file: UploadFile, data: bytes, ext: str) -> Document:
    doc_id = "doc_" + uuid.uuid4().hex[:20]
    doc = Document(
        id=doc_id,
        visitor_id=visitor.id,
        filename=(file.filename or f"upload{ext}")[:255],
        mime=file.content_type or "",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=save_source(doc_id, ext, data),
        status="uploaded",
        stage="queued",
        quality_json={"kind": "source", "courseId": course_id},
    )
    return doc


@router.post("", response_model=CourseOut, status_code=201)
async def create_course(
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
    visitor: Visitor = Depends(get_visitor),
    db: Session = Depends(get_session),
):
    payload = await _read_files(files)

    course_id = "crs_" + uuid.uuid4().hex[:20]
    default_title = f"{Path(payload[0][0].filename or '资料').stem} 合集"
    course_title = (title or "").strip()[:255] or default_title

    course = Course(
        id=course_id,
        visitor_id=visitor.id,
        title=course_title,
        document_id=course_id,
        status="uploaded",
        stage="queued",
    )
    db.add(course)

    # 汇总文档：没有原文件，只有统一页和统一节点；id 与 course 相同，便于直接复用
    # 现有的 outline / play-data 读取逻辑。
    aggregate = Document(
        id=course_id,
        visitor_id=visitor.id,
        filename=course_title,
        mime="application/x-xiaodao-course",
        size_bytes=sum(len(data) for _, data, _ in payload),
        sha256="",
        storage_key="",
        status="uploaded",
        stage="queued",
        quality_json={
            "kind": "course",
            "courseId": course_id,
            "sourceCount": len(payload),
        },
    )
    db.add(aggregate)

    for order, (file, data, ext) in enumerate(payload, start=1):
        source = _new_source_doc(course_id, visitor, file, data, ext)
        db.add(source)
        db.add(CourseSource(course_id=course_id, document_id=source.id, order_index=order))

    db.commit()
    enqueue(db, course_id)
    return _course_out(db, course, aggregate)


@router.get("/{course_id}/status", response_model=CourseOut)
def course_status(course_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    course, doc = _own_course(db, course_id, visitor)
    return _course_out(db, course, doc)


@router.get("/{course_id}/outline", response_model=OutlineOut)
def course_outline(course_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    _, doc = _own_course(db, course_id, visitor)
    return outline_payload(db, doc)


@router.get("/{course_id}/play-data")
def course_play_data(course_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    _, doc = _own_course(db, course_id, visitor)
    data = compat.play_data(db, doc.id)
    if data is None:
        raise HTTPException(status_code=409, detail="合集还没有可用的大纲")
    data["meta"]["courseId"] = course_id
    data["meta"]["sources"] = [
        {"sourceId": item.get("sourceId"), "name": item.get("sourceName"), "pageCount": item.get("pageCount")}
        for item in (doc.quality_json or {}).get("sources", [])
    ]
    return data


@router.post("/{course_id}/sources", response_model=CourseOut, status_code=201)
async def add_course_sources(
    course_id: str,
    files: list[UploadFile] = File(...),
    visitor: Visitor = Depends(get_visitor),
    db: Session = Depends(get_session),
):
    course, doc = _own_course(db, course_id, visitor)
    if doc.status not in ("ready", "partial", "failed"):
        raise HTTPException(status_code=409, detail="合集正在生成，等完成后再补充资料")
    payload = await _read_files(files)
    existing = db.scalars(select(CourseSource).where(CourseSource.course_id == course.id)).all()
    order = max([r.order_index for r in existing], default=0) + 1
    for file, data, ext in payload:
        source = _new_source_doc(course.id, visitor, file, data, ext)
        db.add(source)
        db.add(CourseSource(course_id=course.id, document_id=source.id, order_index=order))
        order += 1

    quality = dict(doc.quality_json or {})
    quality["sourceCount"] = len(existing) + len(payload)
    for obj in (course, doc):
        obj.status = "uploaded"
        obj.stage = "queued"
        obj.progress = 0
        obj.error = None
        obj.quality_json = quality
    db.commit()
    enqueue(db, course.id)
    return _course_out(db, course, doc)


def _delete_doc_rows(db: Session, doc: Document) -> None:
    node_ids = db.scalars(select(Node.id).where(Node.document_id == doc.id)).all()
    if node_ids:
        db.execute(delete(NodePrereq).where(NodePrereq.node_id.in_(node_ids)))
        db.execute(delete(Mark).where(Mark.node_id.in_(node_ids)))
        db.execute(delete(Feedback).where(Feedback.target_id.in_(node_ids)))
    db.execute(delete(DocTask).where(DocTask.document_id == doc.id))
    db.execute(delete(Page).where(Page.document_id == doc.id))
    db.execute(delete(Node).where(Node.document_id == doc.id))
    db.execute(delete(Document).where(Document.id == doc.id))
    delete_document_files(doc.id)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: str, visitor: Visitor = Depends(get_visitor), db: Session = Depends(get_session)):
    course, aggregate = _own_course(db, course_id, visitor)
    rows = db.scalars(select(CourseSource).where(CourseSource.course_id == course.id)).all()
    for row in rows:
        db.execute(delete(CourseSource).where(CourseSource.id == row.id))
        source = db.get(Document, row.document_id)
        if source is not None:
            _delete_doc_rows(db, source)
    _delete_doc_rows(db, aggregate)
    db.execute(delete(Course).where(Course.id == course.id))
    db.commit()
