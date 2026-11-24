"""知识结构化与内容生成（M2）。

流程：节 → 知识点（带出处）→ 前置关系 → 讲解/闯关/题目 → 校验 → 入库。
所有 AI 产出过 schema；出处必须能在对应页原文里回查到。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai import content_hash, get, get_provider, make_key, put, validate
from ..config import settings
from ..models import Document, Node, NodePrereq, Page, UsageEvent

MAX_POINTS_PER_SECTION = 6


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000]+", "", s or "")


def verbatim(excerpt: str, text: str) -> bool:
    e = _norm(excerpt)
    return bool(e) and e in _norm(text)


def _pages_of(db: Session, doc: Document) -> list[Page]:
    return db.scalars(select(Page).where(Page.document_id == doc.id).order_by(Page.page_no)).all()


def _page_text_map(pages: list[Page], offset: int = 0) -> dict[int, str]:
    """印刷页 → 文本。有页码偏移时，跳过没有印刷页码的封面/目录页，避免和正文撞号。"""
    out: dict[int, str] = {}
    for p in pages:
        if p.printed_page is not None:
            key = p.printed_page
        elif offset == 0:
            key = p.page_no
        else:
            continue
        out[key] = out[key] + "\n" + p.text if key in out else p.text
    return out


def _section_text(node: Node, page_map: dict[int, str]) -> tuple[str, list[dict[str, Any]]]:
    # 合集节点在 sources 里保存多个来源页段；普通文档没有，走连续页范围。
    source_refs = [
        item
        for item in (node.sources or [])
        if item.get("type") == "source"
        and item.get("pageStart") is not None
        and item.get("pageEnd") is not None
    ]
    if source_refs:
        chunks: list[dict[str, Any]] = []
        for ref in source_refs:
            start = int(ref.get("pageStart") or 1)
            end = int(ref.get("pageEnd") or start)
            for page in range(start, end + 1):
                text = page_map.get(page, "")
                if text.strip():
                    chunks.append(
                        {
                            "page": page,
                            "text": text,
                            "sourceId": ref.get("sourceId"),
                            "sourceName": ref.get("sourceName"),
                        }
                    )
        joined = "\n".join(c["text"] for c in chunks)
        if joined.strip():
            return joined, chunks

    start = node.page_start or 1
    end = node.page_end or start
    chunks = []
    for page in range(start, end + 1):
        text = page_map.get(page, "")
        if text.strip():
            chunks.append({"page": page, "text": text})
    joined = "\n".join(c["text"] for c in chunks)
    if not joined.strip() and page_map:
        # 页范围对不上（例如骨架页是 PDF 页序）时兜底：取全书前几页
        first = sorted(page_map)[:2]
        chunks = [{"page": p, "text": page_map[p]} for p in first]
        joined = "\n".join(page_map[p] for p in first)
    return joined, chunks


def _section_nodes(db: Session, doc: Document) -> list[Node]:
    return db.scalars(
        select(Node)
        .where(Node.document_id == doc.id, Node.level == "section")
        .order_by(Node.page_start, Node.order_index)
    ).all()


def _ensure_page_text(db: Session, doc: Document, pages: list[Page], sections: list[Node]) -> None:
    """扫描版：只把即将生成内容的那些节覆盖到的页 OCR 回填，别整本跑。"""
    if doc.has_text_layer or not sections:
        return
    from .extract.ocr import get_engine, page_image_relative
    from ..storage.files import source_path

    pdf_path = str(source_path(doc.storage_key))
    by_printed = {p.printed_page: p for p in pages if p.printed_page is not None}
    needed: set[int] = set()
    for s in sections:
        start = s.page_start or 1
        end = s.page_end or start
        needed.update(range(start, end + 1))

    engine = get_engine()
    changed = False
    for printed in sorted(needed):
        pg = by_printed.get(printed)
        if pg is None or pg.text.strip():
            continue
        lines = engine.ocr_page(pdf_path, pg.page_no, doc.id, dpi=settings.ocr_dpi)
        if not lines:
            continue
        lines.sort(key=lambda l: (l.y, l.x))
        pg.text = "\n".join(l.text for l in lines)
        pg.char_count = len(pg.text)
        pg.ocr_confidence = round(sum(l.conf for l in lines) / len(lines), 3)
        pg.image_key = page_image_relative(doc.id, pg.page_no, settings.ocr_dpi)
        changed = True
    if changed:
        db.commit()


def structure_document(db: Session, doc: Document) -> None:
    """节 → 知识点节点。已 locked 的知识点保留，其余重建。"""
    provider = get_provider()
    pages = _pages_of(db, doc)
    sections = _section_nodes(db, doc)[: settings.max_sections_generate]
    _ensure_page_text(db, doc, pages, sections)
    page_map = _page_text_map(pages, doc.page_offset or 0)

    existing = {
        n.id: n
        for n in db.scalars(select(Node).where(Node.document_id == doc.id, Node.level == "knowledge")).all()
    }
    prev_node: Node | None = None

    for section in sections:
        text, chunks = _section_text(section, page_map)
        if not text.strip():
            section.status = "empty"
            section.quality = {"warning": "本节没有可用的正文文本"}
            continue

        key = make_key("extract_points", content_hash(section.id, text), provider.impl_version)
        payload = get(db, key)
        cached = payload is not None
        if payload is None:
            payload = provider.extract_points(section.title, chunks)
            errs = validate("knowledge_points", payload)
            if errs:
                section.status = "failed"
                section.quality = {"schemaErrors": errs[:5]}
                continue
            put(db, key, "extract_points", payload)

        points = payload["points"][:MAX_POINTS_PER_SECTION]
        tag = doc.id[-8:]
        base = f"n_{tag}_{section.path.replace('.', '_')}"
        for k, point in enumerate(points, start=1):
            node_id = f"{base}_{k}"
            old = existing.get(node_id)
            if old is not None and old.locked:
                prev_node = old
                continue
            if old is not None:
                db.delete(old)
                db.flush()

            prereq = []
            same_section_prev = f"{base}_{k - 1}"
            if k > 1:
                prereq.append(same_section_prev)
            elif prev_node is not None:
                prereq.append(prev_node.id)

            node = Node(
                id=node_id,
                document_id=doc.id,
                parent_id=section.id,
                level="knowledge",
                path=f"{section.path}.{k}",
                order_index=k,
                title=point["title"],
                page_start=point["page"],
                page_end=point["page"],
                status="skeleton",
                prerequisites=prereq,
                sources=[{"type": "doc", "page": point["page"], "excerpt": point["excerpt"]}],
                quality={"provider": provider.name, "cached": cached, "type": point["type"], "hint": point.get("importanceHint")},
            )
            db.add(node)
            db.flush()
            for pid in prereq:
                db.merge(NodePrereq(node_id=node.id, prereq_id=pid))
            prev_node = node
        section.status = "structured"
    db.commit()


def _drop_cycles(db: Session, doc: Document) -> list[str]:
    """按 order 线性建边，理论上无环；仍然检测一遍，发现环就拆掉后加的边。"""
    edges = db.scalars(select(NodePrereq)).all()
    node_ids = {n.id for n in db.scalars(select(Node).where(Node.document_id == doc.id))}
    graph: dict[str, list[str]] = {}
    for e in edges:
        if e.node_id in node_ids:
            graph.setdefault(e.node_id, []).append(e.prereq_id)

    removed: list[str] = []
    seen: set[str] = set()
    stack: list[str] = []

    def visit(nid: str) -> bool:
        if nid in stack:
            return True
        if nid in seen:
            return False
        seen.add(nid)
        stack.append(nid)
        for pre in graph.get(nid, []):
            if visit(pre):
                return True
        stack.pop()
        return False

    for nid in list(graph):
        if visit(nid):
            for pre in graph.get(nid, []):
                db.execute(delete(NodePrereq).where(NodePrereq.node_id == nid, NodePrereq.prereq_id == pre))
                removed.append(f"{nid}->{pre}")
            graph[nid] = []
        stack.clear()
        seen.clear()
    db.commit()
    return removed


def _siblings(db: Session, node: Node, points: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for nid, p in points.items() if nid != node.id]


def generate_contents(db: Session, doc: Document, only_node: str | None = None, no_cache: bool = False) -> None:
    provider = get_provider()
    pages = _pages_of(db, doc)
    page_map = _page_text_map(pages, doc.page_offset or 0)

    nodes = db.scalars(
        select(Node).where(Node.document_id == doc.id, Node.level == "knowledge").order_by(Node.path)
    ).all()
    if only_node:
        nodes = [n for n in nodes if n.id == only_node]
    if not nodes:
        return

    points: dict[str, dict[str, Any]] = {}
    for n in nodes:
        src = (n.sources or [{}])[0] if n.sources else {}
        points[n.id] = {
            "title": n.title,
            "definition": _clip_text(src.get("excerpt", "") or n.title, 200),
            "page": int(src.get("page", 1)),
            "excerpt": src.get("excerpt", ""),
            "type": (n.quality or {}).get("type", "concept"),
        }

    for node in nodes:
        if node.locked and only_node is None:
            continue
        siblings = _siblings(db, node, points)
        point = points[node.id]
        section_text = ""
        if node.parent_id:
            parent = db.get(Node, node.parent_id)
            if parent is not None:
                section_text, _ = _section_text(parent, page_map)

        try:
            node.status = "generating"
            db.commit()

            k_content = make_key("explain", content_hash(node.id, point["excerpt"]), provider.impl_version)
            content = None if no_cache else get(db, k_content)
            if content is None:
                content = provider.explain(point, section_text)
                if validate("node_content", content):
                    raise ValueError("讲解未过 schema")
                put(db, k_content, "explain", content)

            k_game = make_key("game", content_hash(node.id, point["excerpt"]), provider.impl_version)
            game = None if no_cache else get(db, k_game)
            if game is None:
                game = provider.make_game(point, siblings)
                if validate("game", game):
                    raise ValueError("闯关内容未过 schema")
                put(db, k_game, "game", game)

            k_q = make_key("questions", content_hash(node.id, point["excerpt"]), provider.impl_version)
            questions = None if no_cache else get(db, k_q)
            if questions is None:
                questions = provider.make_questions(point, siblings, node.id)
                errs = validate("questions", questions)
                if errs:
                    raise ValueError(f"题目未过 schema：{errs[:3]}")
                put(db, k_q, "questions", questions)

            problems = validate_node_content(node, content, game, questions, page_map)
            node.content = {
                "original": content["original"],
                "plain": content["plain"],
                "analogy": content["analogy"],
                "diagramSvg": content.get("diagramSvg"),
            }
            node.game = game
            node.questions = questions
            node.quality = {
                **(node.quality or {}),
                "provider": provider.name,
                "checks": problems or "passed",
                "verified": not provider.is_mock,
            }
            node.status = "ready" if not problems else "partial"
        except Exception as exc:  # noqa: BLE001
            node.status = "failed"
            node.quality = {**(node.quality or {}), "error": f"{type(exc).__name__}: {exc}"[:200]}
            db.commit()
            continue

        db.add(
            UsageEvent(
                visitor_id=doc.visitor_id,
                document_id=doc.id,
                stage="generate",
                model=provider.name,
                in_tokens=0,
                out_tokens=0,
                cost_usd=0.0,
                prompt_version="v1",
            )
        )
        db.commit()

    _drop_cycles(db, doc)


def _clip_text(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n]


def validate_node_content(
    node: Node, content: dict[str, Any], game: dict[str, Any], questions: list[dict[str, Any]], page_map: dict[int, str]
) -> list[str]:
    """出处回查 + 去重。返回问题列表，空表示通过。"""
    problems: list[str] = []
    for src in content.get("sources", []):
        page = int(src.get("page", 0))
        text = page_map.get(page) or next((t for p, t in page_map.items() if p == page), "")
        if not verbatim(str(src.get("excerpt", "")), text):
            problems.append(f"讲解出处未回查到 p{page}")

    kept: list[dict[str, Any]] = []
    stems: set[str] = set()
    ids: set[str] = set()
    for q in questions:
        page = int(q["sourceRef"]["page"])
        text = page_map.get(page, "")
        if not verbatim(q["sourceRef"]["excerpt"], text):
            problems.append(f"题目 {q['id']} 出处未回查到 p{page}")
            continue
        key = _norm(q["stem"])
        if key in stems or q["id"] in ids:
            problems.append(f"题目 {q['id']} 重复，已丢弃")
            continue
        opts = [_norm(o) for o in q.get("options") or []]
        if len(opts) != len(set(opts)):
            problems.append(f"题目 {q['id']} 选项重复，已丢弃")
            continue
        stems.add(key)
        ids.add(q["id"])
        kept.append(q)

    node.questions = kept
    if len(kept) < 3:
        problems.append(f"可用题目只剩 {len(kept)} 道，少于 3 道")
    return problems

