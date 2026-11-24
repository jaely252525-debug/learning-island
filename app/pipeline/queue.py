"""任务队列：用 doc_tasks 表当队列，worker 轮询。MVP 不装 Redis。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import DocTask, utcnow
from .runner import process_document

STALE_SECONDS = 600


def enqueue(db: Session, document_id: str, stage: str = "pipeline") -> DocTask:
    task = DocTask(document_id=document_id, stage=stage, status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _requeue_stale(db: Session) -> None:
    cutoff = utcnow() - dt.timedelta(seconds=STALE_SECONDS)
    for task in db.scalars(select(DocTask).where(DocTask.status == "running")):
        if task.heartbeat is None or task.heartbeat < cutoff:
            task.status = "pending"
            task.error = "心跳超时，已重新排队"
    db.commit()


def process_once() -> bool:
    """取一个 pending 任务跑完；没有任务返回 False。"""
    db = SessionLocal()
    try:
        _requeue_stale(db)
        task = db.scalars(select(DocTask).where(DocTask.status == "pending").order_by(DocTask.id).limit(1)).first()
        if task is None:
            return False
        task.status = "running"
        task.attempts += 1
        task.heartbeat = utcnow()
        db.commit()

        try:
            process_document(db, task.document_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            task.status = "pending" if task.attempts < 3 else "failed"
            task.resume_from = "outlining"
            task.error = f"{type(exc).__name__}: {exc}"[:600]
            db.add(task)
        else:
            task.status = "done"
            task.finished_at = utcnow()
            task.error = None
        db.commit()
        return True
    finally:
        db.close()
