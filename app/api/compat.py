"""给前端原型对齐字段：把后端 Node 结构翻译成原型里的 CH / SC / N / AM / CM。

原型（药用植物岛 · 教材试玩.html）用的常量：
  CH = [[章号, emoji, 短标题, 节数, 起始印刷页], ...]
  SC = {章号: [[短标题, 起始印刷页], ...]}
  N  = {知识点序号: {e,t,pos,pre,pg,o,p,a,svg,g}}
  AM = {知识点序号: 重点理由}   CM = {章号: 重点章节理由}
这里只做字段翻译，不改存储结构；序号在整本书内连续，前置关系同步换成序号。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, Node

CH_EMOJI = ["📖", "🌿", "⚗️", "🥜", "🌾", "🧵", "🧴", "🌸", "☠️", "🎨"]
KNOW_EMOJI = ["🌱", "🍵", "🫧", "🔊", "📡", "👑", "💧", "🔬", "🧪", "🌰", "🪶", "🧊"]

_HIGH_HINT_REASON = "抽取阶段把定义句/小结句标成了高优先级，可作为重点候选。"


def short_title(title: str) -> str:
    """去掉「第1章」「1.1」这类编号，只留标题本身。"""
    t = re.sub(r"^第\s*[一二三四五六七八九十百零〇0-9]+\s*章\s*", "", title or "")
    t = re.sub(r"^\d+(?:\.\d+)*\s*[.、]?\s*", "", t)
    return t.strip()


def page_label(start: int | None, end: int | None) -> str:
    if not start:
        return ""
    if end and end != start:
        return f"{start}–{end}"
    return str(start)


def game_for(node: Node) -> dict[str, Any] | None:
    """后端 {template,payload} → 原型 {type,q,...}。scenario 走 choice。"""
    g = node.game or {}
    tpl = g.get("template")
    p = g.get("payload") or {}
    if tpl == "match":
        return {"type": "match", "q": p.get("q", ""), "pairs": p.get("pairs") or []}
    if tpl == "order":
        return {"type": "order", "q": p.get("q", ""), "steps": p.get("steps") or []}
    if tpl == "scenario":
        opts = p.get("options") or []
        if not opts:
            return None
        return {
            "type": "choice",
            "q": p.get("q", ""),
            "opts": opts,
            "a": int(p.get("answerIndex", 0) or 0),
            "w": p.get("explanation", ""),
        }
    return None


def _layout(k: int, total: int) -> list[int]:
    """一节的据点位置：左右交错，纵向铺开。"""
    if total <= 1:
        return [50, 50]
    x = 50 if total == 3 and k == 1 else (28 if k % 2 == 0 else 72)
    y = round(15 + 70 * k / (total - 1))
    return [x, y]


def number_map(db: Session, doc_id: str) -> dict[str, int]:
    """知识点 id → 全书连续序号（与 N 的键一致）。"""
    nodes = db.scalars(select(Node).where(Node.document_id == doc_id)).all()
    chapters = {
        c.id: i
        for i, c in enumerate(sorted([n for n in nodes if n.level == "chapter"], key=lambda n: n.order_index))
    }
    sections = {s.id: s for s in nodes if s.level == "section"}
    knowledge = [n for n in nodes if n.level == "knowledge"]

    def key(n: Node) -> tuple:
        s = sections.get(n.parent_id)
        return (
            chapters.get(s.parent_id, 0) if s else 0,
            s.order_index if s else 0,
            n.order_index,
        )

    return {n.id: i + 1 for i, n in enumerate(sorted(knowledge, key=key))}


def node_number(db: Session, node: Node) -> int | None:
    return number_map(db, node.document_id).get(node.id)


def play_data(db: Session, doc_id: str) -> dict[str, Any] | None:
    """返回 {CH, SC, N, AM, CM, meta}，可直接给原型用。"""
    nodes = db.scalars(
        select(Node).where(Node.document_id == doc_id).order_by(Node.order_index, Node.id)
    ).all()
    if not nodes:
        return None

    chapters = sorted(
        [n for n in nodes if n.level == "chapter" and n.parent_id is None],
        key=lambda n: n.order_index,
    )
    sections = [n for n in nodes if n.level == "section"]
    knowledge = [n for n in nodes if n.level == "knowledge"]

    chapter_no = {c.id: (i + 1) for i, c in enumerate(chapters)}
    section_no: dict[str, str] = {}
    for c in chapters:
        kids = sorted([s for s in sections if s.parent_id == c.id], key=lambda s: s.order_index)
        for j, s in enumerate(kids):
            section_no[s.id] = f"{chapter_no[c.id]}.{j + 1}"

    def sec_of(node: Node) -> Node | None:
        return next((s for s in sections if s.id == node.parent_id), None)

    def order_key(n: Node) -> tuple:
        s = sec_of(n)
        cno = chapter_no.get(s.parent_id, 0) if s else 0
        return (cno, s.order_index if s else 0, n.order_index)

    nums = number_map(db, doc_id)

    CH = [
        [
            chapter_no[c.id],
            CH_EMOJI[(chapter_no[c.id] - 1) % len(CH_EMOJI)],
            short_title(c.title),
            sum(1 for s in sections if s.parent_id == c.id),
            c.page_start or 1,
        ]
        for c in chapters
    ]

    SC = {
        str(chapter_no[c.id]): [
            [short_title(s.title), s.page_start or 1]
            for s in sorted(sections, key=lambda s: s.order_index)
            if s.parent_id == c.id
        ]
        for c in chapters
    }

    N: dict[str, Any] = {}
    AM: dict[str, str] = {}
    for i, n in enumerate(sorted(knowledge, key=order_key)):
        content = n.content or {}
        plain = content.get("plain") or []
        siblings = [k for k in sorted(knowledge, key=order_key) if k.parent_id == n.parent_id]
        k = next((j for j, x in enumerate(siblings) if x.id == n.id), 0)
        item: dict[str, Any] = {
            "e": KNOW_EMOJI[i % len(KNOW_EMOJI)],
            "t": short_title(n.title),
            "pos": _layout(k, len(siblings)),
            "pre": [nums[p] for p in (n.prerequisites or []) if p in nums],
            "pg": page_label(n.page_start, n.page_end),
            "o": content.get("original", ""),
            "p": plain[1] if len(plain) > 1 else (plain[0] if plain else ""),
            "a": content.get("analogy", ""),
            "svg": content.get("diagramSvg"),
            "g": game_for(n),
            "id": n.id,
            "sid": section_no.get(n.parent_id or "", ""),
            "sources": n.sources or [],
            "status": n.status,
        }
        N[str(nums[n.id])] = item
        if (n.quality or {}).get("hint") == "high":
            AM[str(nums[n.id])] = _HIGH_HINT_REASON

    CM = {
        str(chapter_no[c.id]): (c.importance or {}).get("reason", "")
        for c in chapters
        if (c.importance or {}).get("reason")
    }

    doc = db.get(Document, doc_id)
    quality = (doc.quality_json if doc else None) or {}
    return {
        "CH": CH,
        "SC": SC,
        "N": N,
        "AM": AM,
        "CM": CM,
        "meta": {
            "docId": doc_id,
            "filename": doc.filename if doc else "",
            "title": quality.get("courseTitle") or "",
            "courseId": quality.get("courseId", ""),
            "sourceCount": len(quality.get("sources") or []),
            "chapters": len(chapters),
            "sections": len(sections),
            "knowledge": len(knowledge),
            "pending": sum(1 for n in knowledge if n.status != "ready"),
        },
    }
