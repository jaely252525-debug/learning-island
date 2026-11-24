"""流水线执行：提取 → 骨架 → 知识点 → 生成 → 校验。阶段失败可断点续跑。"""
from __future__ import annotations

import traceback
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Document, Node, NodePrereq, Page, utcnow
from ..storage.files import source_path
from .extract import extract
from .generate import generate_contents, structure_document
from .outline.build import build_skeleton

ORDER = {
    "uploaded": 0,
    "extracting": 1,
    "outlining": 2,
    "structuring": 3,
    "generating": 4,
    "validating": 5,
    "ready": 6,
    "partial": 6,
    "failed": 6,
}


def _set_stage(doc: Document, status: str, stage: str, progress: int) -> None:
    doc.status = status
    doc.stage = stage
    doc.progress = progress
    doc.error = None
    doc.updated_at = utcnow()


def _store_pages(db: Session, doc: Document, result) -> None:
    db.execute(delete(Page).where(Page.document_id == doc.id))
    for p in result.pages:
        db.add(
            Page(
                document_id=doc.id,
                page_no=p.page_no,
                printed_page=p.printed_page,
                text=p.text,
                char_count=p.char_count,
                ocr_confidence=p.ocr_confidence,
                image_key=p.image_key,
            )
        )
    doc.page_count = result.page_count
    doc.page_offset = result.page_offset
    doc.has_text_layer = result.has_text_layer
    doc.quality_json = {
        **(doc.quality_json or {}),
        "method": result.method,
        "warnings": result.warnings,
        "ocr": result.stats,
        # teeth 存下来，断点续跑不用重解析原文件
        "teeth": [{"level": t.level, "title": t.title, "page": t.page, "order": t.order} for t in result.teeth],
    }


def _doc_tag(doc_id: str) -> str:
    """节点 id 是全局主键，必须带文档前缀，否则第二个文档的 ch_1 会撞车。"""
    return doc_id[-8:]


def _store_skeleton(db: Session, doc: Document, chapters) -> tuple[int, int]:
    # 先批量删掉旧骨架（SQLAlchemy 一次 flush 里 INSERT 在 DELETE 之前，容易撞主键）
    old_skel = db.scalars(
        select(Node.id).where(
            Node.document_id == doc.id,
            Node.level.in_(("chapter", "section")),
            Node.locked == False,  # noqa: E712
        )
    ).all()
    for nid in old_skel:
        db.execute(delete(NodePrereq).where(NodePrereq.node_id == nid))
    if old_skel:
        db.execute(delete(Node).where(Node.id.in_(old_skel)))
        db.flush()
    existing = {n.id: n for n in db.scalars(select(Node).where(Node.document_id == doc.id))}

    offset = doc.page_offset or 0
    tag = _doc_tag(doc.id)
    chapters_n = sections_n = 0
    for c in chapters:
        ch_id = f"ch_{tag}_{c.order}"
        if ch_id in existing and existing[ch_id].locked:
            continue
        db.add(
            Node(
                id=ch_id,
                document_id=doc.id,
                parent_id=None,
                level="chapter",
                path=f"{c.order}",
                order_index=c.order,
                title=c.title,
                page_start=max(1, c.page_start - offset),
                page_end=max(1, c.page_end - offset),
                status="skeleton",
                prerequisites=[],
            )
        )
        chapters_n += 1
        for s in c.sections:
            sec_id = f"sec_{tag}_{c.order}_{s.order}"
            if sec_id in existing and existing[sec_id].locked:
                continue
            db.add(
                Node(
                    id=sec_id,
                    document_id=doc.id,
                    parent_id=ch_id,
                    level="section",
                    path=f"{c.order}.{s.order}",
                    order_index=s.order,
                    title=s.title,
                    page_start=max(1, s.page_start - offset),
                    page_end=max(1, s.page_end - offset),
                    status="skeleton",
                    prerequisites=[],
                )
            )
            sections_n += 1
    return chapters_n, sections_n


def _has_nodes(db: Session, doc: Document, level: str) -> bool:
    return db.scalar(select(Node.id).where(Node.document_id == doc.id, Node.level == level).limit(1)) is not None


def _finalize(db: Session, doc: Document) -> None:
    nodes = db.scalars(select(Node).where(Node.document_id == doc.id, Node.level == "knowledge")).all()
    statuses = [n.status for n in nodes]
    quality = dict(doc.quality_json or {})
    quality["nodes"] = {
        "total": len(nodes),
        "ready": statuses.count("ready"),
        "partial": statuses.count("partial"),
        "failed": statuses.count("failed"),
    }

    # 章节状态跟着知识点走，前端一眼就能看出哪座岛能玩
    for section in db.scalars(select(Node).where(Node.document_id == doc.id, Node.level == "section")).all():
        kids = [n for n in nodes if n.parent_id == section.id]
        if not kids:
            section.status = section.status if section.status in ("empty", "failed") else "skeleton"
        elif all(k.status == "ready" for k in kids):
            section.status = "ready"
        elif any(k.status == "failed" for k in kids):
            section.status = "partial"
        else:
            section.status = "partial" if kids else section.status
    for chapter in db.scalars(select(Node).where(Node.document_id == doc.id, Node.level == "chapter")).all():
        kids = [n for n in db.scalars(select(Node).where(Node.document_id == doc.id, Node.level == "section", Node.parent_id == chapter.id)).all()]
        chapter.status = "ready" if kids and all(k.status == "ready" for k in kids) else "partial"

    doc.quality_json = quality
    if not nodes:
        _set_stage(doc, "partial", "done", 100)
        quality["warning"] = "没有生成任何知识点，检查解析文本"
        doc.quality_json = quality
    elif "failed" in statuses or "partial" in statuses:
        _set_stage(doc, "partial", "done", 100)
    else:
        _set_stage(doc, "ready", "done", 100)


def process_document(db: Session, doc_id: str, stop_after: str | None = None) -> None:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"文档不存在：{doc_id}")

    try:
        if (doc.quality_json or {}).get("kind") == "course":
            from .course import process_course

            process_course(db, doc)
            return

        if ORDER.get(doc.status, 0) >= ORDER["ready"]:
            return

        pages_exist = db.scalar(select(Page.page_no).where(Page.document_id == doc.id).limit(1)) is not None

        # —— 提取 ——
        if not pages_exist or ORDER.get(doc.status, 0) < ORDER["extracting"]:
            _set_stage(doc, "extracting", "extract", 15)
            db.commit()
            if not doc.storage_key or not source_path(doc.storage_key).exists():
                raise FileNotFoundError("原文件已丢失，无法解析")
            result = extract(str(source_path(doc.storage_key)), doc.id)
            _store_pages(db, doc, result)
            _set_stage(doc, "outlining", "outline", 55)
            db.commit()

        # —— 骨架 ——
        if ORDER.get(doc.status, 0) <= ORDER["outlining"] or not _has_nodes(db, doc, "chapter"):
            _set_stage(doc, "outlining", "outline", 60)
            db.commit()
            teeth = _teeth_from_quality(doc)
            fallback = Path(doc.filename).stem or "未识别目录"
            chapters = build_skeleton(teeth, doc.page_count or 1, fallback_title=fallback)
            chapters_n, sections_n = _store_skeleton(db, doc, chapters)
            quality = dict(doc.quality_json or {})
            quality.update({"chapters": chapters_n, "sections": sections_n})
            doc.quality_json = quality
            _set_stage(doc, "structuring", "structure", 68)
            db.commit()

        if stop_after == "outline":
            # 合集来源只需要页文本和章/节骨架，不单独生成知识点，避免重复付费。
            quality = dict(doc.quality_json or {})
            quality["stopAfter"] = "outline"
            doc.quality_json = quality
            _set_stage(doc, "ready", "done", 100)
            db.commit()
            return
        if ORDER.get(doc.status, 0) <= ORDER["structuring"]:
            _set_stage(doc, "structuring", "structure", 72)
            db.commit()
            structure_document(db, doc)
            _set_stage(doc, "generating", "generate", 78)
            db.commit()

        # —— 讲解 / 闯关 / 题目 ——
        if ORDER.get(doc.status, 0) <= ORDER["generating"]:
            _set_stage(doc, "generating", "generate", 80)
            db.commit()
            generate_contents(db, doc)
            _set_stage(doc, "validating", "validate", 95)
            db.commit()

        # —— 汇总状态 ——
        if ORDER.get(doc.status, 0) <= ORDER["validating"]:
            _finalize(db, doc)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = "failed"
            doc.stage = "failed"
            doc.error = f"{type(exc).__name__}: {exc}"[:800]
            db.add(doc)
            db.commit()
            from ..models import Course

            course = db.get(Course, doc.id)
            if course is not None:
                course.status = doc.status
                course.stage = doc.stage
                course.progress = doc.progress
                course.error = doc.error
                course.quality_json = doc.quality_json or {}
                db.add(course)
                db.commit()
        traceback.print_exc()
        raise


def _teeth_from_quality(doc: Document) -> list:
    from .extract.common import Tooth

    stored = (doc.quality_json or {}).get("teeth") or []
    return [
        Tooth(level=int(t["level"]), title=t["title"], page=int(t["page"]), order=int(t["order"]))
        for t in stored
    ]
