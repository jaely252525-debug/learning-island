"""目录页识别：从扫描版的目录 OCR 出「章 / 节 + 印刷页码」。

只认两级：章（1 绪论）和节（1.1 xxx）；1.1.1 这类三级条目跳过，也不进骨架。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..extract.ocr import OcrLine

if TYPE_CHECKING:
    from ..extract.common import Tooth

_SUBSECTION = re.compile(r"^\d{1,2}[.．]\d{1,2}[.．]\d{1,2}")
_SECTION = re.compile(r"^(\d{1,2})[.．](\d{1,2})(.*)$")
_NUM_SEP = " .、:：;；,，·•*#-–—_~·\t"
_CHAPTER = re.compile(r"^(\d{1,2})(?![.．\d])\s*([^\d].*)$")
_PAGE_TOKEN = re.compile(r"^[(（]\s*(\d{1,4})\s*[)）]$")
_BARE_NUM = re.compile(r"^\d{1,4}$")
_CJK = re.compile(r"[一-鿿]")
_SPLIT_NUM = re.compile(r"^\d{1,2}[.．]$")


_HEADING_NOISE = ("目录", "目次", "参考文献", "前言", "附录", "索引")


@dataclass
class Row:
    chapter: tuple[int, str, int | None] | None = None
    section: tuple[int, int, str, int | None] | None = None
    heading: tuple[str, int] | None = None  # 疑似章标题但 OCR 丢了章号
    conf: float = 1.0
    y: float = 0.0


def _row_tolerance(lines: list[OcrLine]) -> tuple[float, float]:
    heights = sorted(l.h for l in lines if l.h > 0)
    med_h = heights[len(heights) // 2] if heights else 40.0
    return max(10.0, med_h * 0.62), med_h


def _group_rows(lines: list[OcrLine], tol: float) -> list[list[OcrLine]]:
    ordered = sorted(lines, key=lambda l: (l.y, l.x))
    rows: list[list[OcrLine]] = []
    for line in ordered:
        if rows and abs(rows[-1][0].y - line.y) <= tol:
            rows[-1].append(line)
        else:
            rows.append([line])
    for r in rows:
        r.sort(key=lambda l: l.x)
    return rows


def _clean(title: str) -> str:
    title = title.replace("·", "").replace("…", "").replace("⋯", "").replace("#", "").replace("*", "")
    title = re.sub(r"[(（]\s*\d{1,4}\s*[)）]", "", title)
    title = re.sub(r"\s+", " ", title).strip(" .·-—")
    return title[:60]


def parse_toc_rows(lines: list[OcrLine], page_width: float = 1.0, right_band: float = 0.62) -> list[Row]:
    tol, _ = _row_tolerance(lines)
    rows = _group_rows(lines, tol)
    entities: list[Row] = []

    for tokens in rows:
        page: int | None = None
        body: list[OcrLine] = []
        for t in tokens:
            m = _PAGE_TOKEN.match(t.text.strip())
            if m:
                page = int(m.group(1))
                continue
            if t.x > page_width * right_band and _BARE_NUM.match(t.text.strip()):
                page = int(t.text.strip())
                continue
            body.append(t)

        start = len(entities)
        # 编号被 OCR 拆成两截（"1." + "1"）时先拼回去
        merged: list[OcrLine] = []
        i = 0
        while i < len(body):
            t = body[i]
            s = t.text.strip()
            if _SPLIT_NUM.match(s) and i + 1 < len(body) and re.match(r"^\d{1,2}(?!\d)", body[i + 1].text.strip()):
                merged.append(OcrLine(text=s + body[i + 1].text.strip(), x=t.x, y=t.y, conf=t.conf, h=t.h))
                i += 2
                continue
            # 章号被单独识别成一格（"10" + "富色素…"）时拼回去
            if (
                re.fullmatch(r"\d{1,2}", s)
                and i + 1 < len(body)
                and _CJK.match(body[i + 1].text.strip()[:1] or " ")
                and body[i + 1].x - t.x < page_width * 0.35
            ):
                merged.append(OcrLine(text=s + body[i + 1].text.strip(), x=t.x, y=t.y, conf=t.conf, h=t.h))
                i += 2
                continue
            merged.append(t)
            i += 1

        for t in merged:
            norm = re.sub(r"\s+", "", t.text)
            if not norm:
                continue
            if _SUBSECTION.match(norm):
                continue  # 三级标题：跳过，也不当标题续行
            m = _SECTION.match(norm)
            if m:
                rest = m.group(3).lstrip(_NUM_SEP).strip()
                if not rest or _CJK.search(rest):
                    title = _clean(rest)
                    entities.append(
                        Row(section=(int(m.group(1)), int(m.group(2)), title, page), conf=t.conf, y=t.y)
                    )
                    continue
            m = _CHAPTER.match(norm) if t.x < page_width * 0.30 else None
            if m:
                rest = m.group(2).strip()
                if _CJK.search(rest):
                    entities.append(Row(chapter=(int(m.group(1)), _clean(rest), page), conf=t.conf, y=t.y))
                    continue
            # 其余当标题续行：只贴到同一行的实体
            if entities and abs(entities[-1].y - t.y) <= tol:
                last = entities[-1]
                if last.section:
                    cno, sno, old, pg = last.section
                    merged = _clean(f"{old}{t.text}")
                    entities[-1] = Row(section=(cno, sno, merged, pg), conf=min(last.conf, t.conf), y=last.y)
                elif last.chapter:
                    no, old, pg = last.chapter
                    merged = _clean(f"{old}{t.text}")
                    entities[-1] = Row(chapter=(no, merged, pg), conf=min(last.conf, t.conf), y=last.y)

        # 疑似章标题但 OCR 把章号丢了（示例书第 5、10 章就是这样）
        if len(entities) == start and page is not None and body:
            first = body[0]
            txt = _clean(first.text)
            if (
                first.x < page_width * 0.17
                and len(_CJK.findall(txt)) >= 5
                and not any(k in txt for k in _HEADING_NOISE)
            ):
                entities.append(Row(heading=(txt, page), conf=first.conf, y=first.y))

        if page is not None:
            for e in entities[start:]:
                if e.section and e.section[3] is None:
                    cno, sno, title, _ = e.section
                    e.section = (cno, sno, title, page)
                elif e.chapter and e.chapter[2] is None:
                    no, title, _ = e.chapter
                    e.chapter = (no, title, page)

    # 章标题被拆成两行的情况：标题过短就吞并下一个纯标题实体
    for i, e in enumerate(entities):
        if not e.chapter:
            continue
        no, title, page = e.chapter
        if len(title) <= 4 and i + 1 < len(entities):
            nxt = entities[i + 1]
            if nxt.section and i + 1 < len(entities):
                continue
            if nxt.chapter:
                _, nt, _ = nxt.chapter
                if nt.startswith(title):
                    entities[i] = Row(chapter=(no, nt, page or nxt.chapter[2]), conf=e.conf, y=e.y)
                    continue
                entities[i] = Row(chapter=(no, _clean(title + nt), page or nxt.chapter[2]), conf=e.conf, y=e.y)
    return _resolve_headings(entities)


def _resolve_headings(entities: list[Row]) -> list[Row]:
    """把「丢了章号的标题行」补成章：它后面紧跟的第 1 节，章号就是答案。"""
    out: list[Row] = []
    last_no = 0
    pending: Row | None = None
    for e in entities:
        if e.heading:
            pending = e
            continue
        if e.chapter:
            last_no = e.chapter[0]
            pending = None
            out.append(e)
            continue
        if e.section:
            cno, sno, _title, page = e.section
            if sno == 1 and cno > last_no and pending is not None and page is not None:
                out.append(
                    Row(chapter=(cno, pending.heading[0], pending.heading[1]), conf=pending.conf, y=pending.y)
                )
                last_no = cno
            pending = None
            out.append(e)
            continue
        out.append(e)
    # 页码都没有的行基本是正文误入（页宽右带没截到页码），直接丢掉
    return [e for e in out if (e.chapter and e.chapter[2]) or (e.section and e.section[3])]


def dedupe(rows: list[Row]) -> list[Row]:
    seen: set[tuple] = set()
    out: list[Row] = []
    for r in rows:
        key = ("c", r.chapter[0]) if r.chapter else ("s", r.section[0], r.section[1])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def rows_to_teeth(rows: list[Row], offset: int) -> list["Tooth"]:
    from ..extract.common import Tooth

    teeth: list["Tooth"] = []
    order = 0
    for e in rows:
        if e.chapter:
            no, title, page = e.chapter
            label = f"第{no}章 {title}".strip()
            teeth.append(Tooth(level=1, title=label, page=max(1, (page or 1) + offset), order=order))
            order += 1
        elif e.section:
            cno, sno, title, page = e.section
            label = f"{cno}.{sno} {title}".strip()
            teeth.append(Tooth(level=2, title=label, page=max(1, (page or 1) + offset), order=order))
            order += 1
    return teeth


def summarise(rows: list[Row]) -> dict[str, Any]:
    chapters = [r for r in rows if r.chapter]
    sections = [r for r in rows if r.section]
    counts: dict[int, int] = {}
    for r in sections:
        counts[r.section[0]] = counts.get(r.section[0], 0) + 1
    return {
        "chapters": len(chapters),
        "sections": len(sections),
        "sectionsPerChapter": counts,
        "lowConfidenceRows": sum(1 for r in rows if r.conf < 0.6),
        "missingPages": sum(1 for r in rows if (r.chapter and r.chapter[2] is None) or (r.section and r.section[3] is None)),
    }
