"""多资料合集流水线：先解析各来源，再合成统一页面、大纲、知识点和题目。

存储上仍然复用 Document / Page / Node：
- CourseSource 指向每个原始文件对应的 Document（只解析到大纲，不单独生成内容）；
- Course.document_id 指向一个“汇总 Document”，它的 Page 是各来源页按顺序拼成的
 全局页，Node 挂在这个汇总 Document 下，因此 outline / play-data 可直接复用。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai import get_provider, validate
from ..ai.outline_merge import merge_outline_sources
from ..models import (
    Course,
    CourseSource,
    Document,
    Feedback,
    Mark,
    Node,
    NodePrereq,
    Page,
    utcnow,
)
from .generate import generate_contents, structure_document


def _set_stage(db: Session, course: Course, doc: Document, status: str, stage: str, progress: int) -> None:
    for obj in (course, doc):
        obj.status = status
        obj.stage = stage
        obj.progress = progress
        obj.error = None
        obj.updated_at = utcnow()
    db.commit()


def _sync_course(course: Course, doc: Document) -> None:
    course.status = doc.status
    course.stage = doc.stage
    course.progress = doc.progress
    course.error = doc.error
    course.quality_json = doc.quality_json or {}


def _source_docs(db: Session, course: Course) -> list[tuple[CourseSource, Document]]:
    rows = db.scalars(
        select(CourseSource).where(CourseSource.course_id == course.id).order_by(CourseSource.order_index, CourseSource.id)
    ).all()
    out: list[tuple[CourseSource, Document]] = []
    for row in rows:
        doc = db.get(Document, row.document_id)
        if doc is None:
            raise ValueError(f"合集来源不存在：{row.document_id}")
        out.append((row, doc))
    if not out:
        raise ValueError("合集没有来源文件")
    return out


def _reset_course_nodes(db: Session, doc: Document) -> None:
    node_ids = db.scalars(select(Node.id).where(Node.document_id == doc.id)).all()
    if node_ids:
        db.execute(delete(NodePrereq).where(NodePrereq.node_id.in_(node_ids)))
        db.execute(delete(Mark).where(Mark.node_id.in_(node_ids)))
        db.execute(delete(Feedback).where(Feedback.target_id.in_(node_ids)))
    db.execute(delete(Node).where(Node.document_id == doc.id))
    db.commit()


def _store_course_pages(db: Session, course: Course, doc: Document, sources) -> list[dict]:
    db.execute(delete(Page).where(Page.document_id == doc.id))
    global_no = 0
    ranges: list[dict] = []

    for row, src in sources:
        pages = db.scalars(
            select(Page).where(Page.document_id == src.id).order_by(Page.page_no)
        ).all()
        if not pages:
            continue
        start = global_no + 1
        for page in pages:
            global_no += 1
            text = page.text or ""
            db.add(
                Page(
                    document_id=doc.id,
                    page_no=global_no,
                    printed_page=global_no,
                    text=text,
                    char_count=len(text),
                    ocr_confidence=page.ocr_confidence,
                )
            )
        ranges.append(
            {
                "sourceId": src.id,
                "sourceName": src.filename,
                "sourceOrder": row.order_index,
                "globalStart": start,
                "globalEnd": global_no,
                "sourcePageStart": pages[0].page_no,
                "sourcePageEnd": pages[-1].page_no,
                "pageCount": len(pages),
            }
        )

    doc.page_count = global_no
    doc.page_offset = 0
    doc.has_text_layer = True
    quality = dict(doc.quality_json or {})
    quality.update(
        {
            "kind": "course",
            "courseId": course.id,
            "sources": ranges,
        }
    )
    doc.quality_json = quality
    if global_no == 0:
        raise ValueError("所有来源都没有解析出页面")
    db.commit()
    return ranges


def _source_page(src: Document, page: int | None) -> int:
    value = int(page or 1) + int(src.page_offset or 0)
    return max(1, min(int(src.page_count or 1), value))


def _nodes_of(db: Session, doc: Document) -> list[Node]:
    return db.scalars(select(Node).where(Node.document_id == doc.id)).all()


def _fill_source_ocr(db: Session, src: Document) -> None:
    """扫描版 PDF 的来源只解析到 TOC，正文页还是空的；合集合并前补齐。"""
    if src.has_text_layer or not src.storage_key:
        return
    from ..config import settings
    from ..storage.files import source_path
    from .extract.ocr import get_engine, page_image_relative

    pages = db.scalars(select(Page).where(Page.document_id == src.id).order_by(Page.page_no)).all()
    if not pages:
        return
    engine = get_engine()
    pdf_path = str(source_path(src.storage_key))
    changed = False
    for page in pages:
        if page.text.strip():
            continue
        lines = engine.ocr_page(pdf_path, page.page_no, src.id, dpi=settings.ocr_dpi)
        if not lines:
            continue
        lines.sort(key=lambda line: (line.y, line.x))
        page.text = "\n".join(line.text for line in lines)
        page.char_count = len(page.text)
        page.ocr_confidence = round(sum(line.conf for line in lines) / len(lines), 3)
        page.image_key = page_image_relative(src.id, page.page_no, settings.ocr_dpi)
        changed = True
    if changed:
        db.commit()


def _make_source_outline(course: Course, src: Document, nodes: list[Node]) -> dict:
    chapters = sorted([n for n in nodes if n.level == "chapter"], key=lambda n: n.order_index)
    sections = [n for n in nodes if n.level == "section"]
    teeth = (src.quality_json or {}).get("teeth") or []
    only_section_titles = bool(teeth) and all(int(t.get("level", 2)) == 2 for t in teeth)
    out_chapters: list[dict] = []
    for chapter in chapters:
        chapter_title = chapter.title
        if len(chapters) == 1 and only_section_titles:
            # PPT 没有真正的章标题时，不要拿文件名当章名，否则多份 PPT
            # 会被误判成两个不同的章，永远合并不了。
            chapter_title = "全文"
        rows = []
        for section in sorted([s for s in sections if s.parent_id == chapter.id], key=lambda s: s.order_index):
            start = _source_page(src, section.page_start)
            end = max(start, _source_page(src, section.page_end))
            rows.append({"title": section.title, "pageStart": start, "pageEnd": end})
        if rows:
            out_chapters.append({"title": chapter_title, "sections": rows})
    if not out_chapters:
        out_chapters = [
            {
                "title": "全文",
                "sections": [{"title": "全部内容", "pageStart": 1, "pageEnd": max(1, src.page_count)}],
            }
        ]
    return {
        "sourceId": src.id,
        "title": Path(src.filename).stem or src.filename,
        "courseTitle": course.title,
        "pageCount": max(1, src.page_count),
        "chapters": out_chapters,
    }


def _locator(ranges: list[dict]) -> dict[int, tuple[dict, int]]:
    out: dict[int, tuple[dict, int]] = {}
    for item in ranges:
        start = int(item["globalStart"])
        end = int(item["globalEnd"])
        source_start = int(item["sourcePageStart"])
        for page in range(start, end + 1):
            out[page] = (item, source_start + page - start)
    return out


def _plans_from_merged(merged: dict, ranges: list[dict]) -> list[dict]:
    by_source = {r["sourceId"]: r for r in ranges}
    chapters: list[dict] = []
    for chapter in merged.get("chapters") or []:
        sections: list[dict] = []
        for section in chapter.get("sections") or []:
            refs: list[dict] = []
            for ref in section.get("refs") or []:
                src_range = by_source.get(str(ref.get("sourceId") or ""))
                if src_range is None:
                    continue
                start_raw = int(ref.get("pageStart") or 1)
                end_raw = int(ref.get("pageEnd") or start_raw)
                if start_raw > end_raw:
                    start_raw, end_raw = end_raw, start_raw
                if end_raw < int(src_range["sourcePageStart"]) or start_raw > int(src_range["sourcePageEnd"]):
                    continue
                start_raw = max(int(src_range["sourcePageStart"]), start_raw)
                end_raw = min(int(src_range["sourcePageEnd"]), end_raw)
                shift = int(src_range["globalStart"]) - int(src_range["sourcePageStart"])
                refs.append(
                    {
                        "type": "source",
                        "sourceId": src_range["sourceId"],
                        "sourceName": src_range["sourceName"],
                        "pageStart": start_raw + shift,
                        "pageEnd": end_raw + shift,
                        "sourcePageStart": start_raw,
                        "sourcePageEnd": end_raw,
                    }
                )
            if not refs:
                continue
            sections.append(
                {
                    "title": str(section.get("title") or "本节内容"),
                    "page_start": min(r["pageStart"] for r in refs),
                    "page_end": max(r["pageEnd"] for r in refs),
                    "sources": refs,
                }
            )
        if sections:
            chapters.append({"title": str(chapter.get("title") or "综合资料"), "sections": sections})
    return chapters


def _store_course_skeleton(db: Session, doc: Document, chapters: list[dict]) -> tuple[int, int]:
    tag = doc.id[-8:]
    chapters_n = sections_n = 0
    for c_order, chapter in enumerate(chapters, start=1):
        chapter_id = f"ch_{tag}_{c_order}"
        db.add(
            Node(
                id=chapter_id,
                document_id=doc.id,
                parent_id=None,
                level="chapter",
                path=str(c_order),
                order_index=c_order,
                title=str(chapter["title"])[:255],
                page_start=max(1, min(s["page_start"] for s in chapter["sections"])),
                page_end=max(1, max(s["page_end"] for s in chapter["sections"])),
                status="skeleton",
                prerequisites=[],
            )
        )
        chapters_n += 1
        for s_order, section in enumerate(chapter["sections"], start=1):
            db.add(
                Node(
                    id=f"sec_{tag}_{c_order}_{s_order}",
                    document_id=doc.id,
                    parent_id=chapter_id,
                    level="section",
                    path=f"{c_order}.{s_order}",
                    order_index=s_order,
                    title=str(section["title"])[:255],
                    page_start=max(1, section["page_start"]),
                    page_end=max(1, section["page_end"]),
                    status="skeleton",
                    prerequisites=[],
                    sources=section.get("sources") or [],
                )
            )
            sections_n += 1
    db.commit()
    return chapters_n, sections_n


def _annotate_course_sources(db: Session, doc: Document, ranges: list[dict]) -> None:
    locator = _locator(ranges)
    for node in db.scalars(select(Node).where(Node.document_id == doc.id)).all():
        if node.level != "knowledge":
            continue
        items = []
        for item in node.sources or []:
            loc = locator.get(int(item.get("page") or 0))
            if loc:
                source_range, source_page = loc
                item = {
                    **item,
                    "sourceId": source_range["sourceId"],
                    "sourceName": source_range["sourceName"],
                    "sourcePage": source_page,
                    "globalPage": int(item.get("page") or 0),
                }
            items.append(item)
        node.sources = items
        questions = []
        for question in node.questions or []:
            ref = question.get("sourceRef") if isinstance(question, dict) else None
            if isinstance(ref, dict):
                loc = locator.get(int(ref.get("page") or 0))
                if loc:
                    source_range, source_page = loc
                    question = {
                        **question,
                        "sourceRef": {
                            **ref,
                            "sourceId": source_range["sourceId"],
                            "sourceName": source_range["sourceName"],
                            "sourcePage": source_page,
                            "globalPage": int(ref.get("page") or 0),
                        },
                    }
            questions.append(question)
        node.questions = questions
    db.commit()


def process_course(db: Session, doc: Document) -> None:
    course = db.get(Course, doc.id)
    if course is None:
        raise ValueError(f"合集不存在：{doc.id}")
    sources = _source_docs(db, course)
    from .runner import process_document  # 避免 runner ↔ course 循环导入

    # 1) 各来源只解析到“页 + 章/节骨架”，不重复生成内容。
    _set_stage(db, course, doc, "extracting", "merge_sources", 20)
    for row, src in sources:
        if src.status not in ("failed",):
            process_document(db, src.id, stop_after="outline")
        if src.status == "failed":
            raise ValueError(f"来源解析失败：{src.filename}：{src.error or ''}")
        _fill_source_ocr(db, src)

    # 2) 合成全局页，并记录来源页到全局页的映射。
    _set_stage(db, course, doc, "outlining", "merge_pages", 50)
    ranges = _store_course_pages(db, course, doc, sources)

    # 3) 合并大纲。真模型走 merge_outline；mock / 非法输出回退到标题聚类。
    _set_stage(db, course, doc, "outlining", "merge_outline", 60)
    payload = []
    for row, src in sources:
        payload.append(_make_source_outline(course, src, _nodes_of(db, src)))
    provider = get_provider()
    merged = None
    merge_method = "fallback"
    try:
        candidate = provider.merge_outline(payload)
        if not validate("course_outline", candidate):
            merged = candidate
            merge_method = "ai" if not getattr(provider, "is_mock", False) else "title_cluster"
    except Exception:
        merged = None
    if merged is None:
        merged = merge_outline_sources(payload)

    chapters = _plans_from_merged(merged, ranges)
    if not chapters:
        merged = merge_outline_sources(payload)
        chapters = _plans_from_merged(merged, ranges)
    if not chapters:
        raise ValueError("无法合并出统一大纲")

    _reset_course_nodes(db, doc)
    chapters_n, sections_n = _store_course_skeleton(db, doc, chapters)
    quality = dict(doc.quality_json or {})
    quality.update(
        {
            "merge": {"method": merge_method, "provider": getattr(provider, "name", "mock")},
            "chapters": chapters_n,
            "sections": sections_n,
            "courseTitle": merged.get("title") or course.title,
        }
    )
    doc.quality_json = quality
    course.quality_json = quality
    course.updated_at = utcnow()
    db.commit()

    # 4) 复用原来的知识点/讲解/闯关/题目生成。
    _set_stage(db, course, doc, "structuring", "structure", 72)
    structure_document(db, doc)
    _set_stage(db, course, doc, "generating", "generate", 80)
    generate_contents(db, doc)
    _annotate_course_sources(db, doc, ranges)

    from .runner import _finalize

    _finalize(db, doc)
    _sync_course(course, doc)
    db.commit()
