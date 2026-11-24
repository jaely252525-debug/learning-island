"""骨架：把目录/标题清单变成 章 → 节 两层结构。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extract.common import Tooth
from .page_offset import pick_offset


@dataclass
class SectionPlan:
    title: str
    page_start: int
    page_end: int
    order: int


@dataclass
class ChapterPlan:
    title: str
    page_start: int
    page_end: int
    order: int
    sections: list[SectionPlan] = field(default_factory=list)


def _tidy(title: str, fallback: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip(" ·.-—")
    if not title:
        return fallback
    return title[:120]


def build_skeleton(teeth: list[Tooth], page_count: int, fallback_title: str = "未识别目录") -> list[ChapterPlan]:
    page_count = max(1, page_count)
    ordered = [t for t in teeth if 1 <= t.page <= page_count]
    ordered.sort(key=lambda t: (t.page, t.order))

    has_chapters = any(t.level == 1 for t in ordered)

    if not has_chapters and ordered:
        # 只有节级标题：包一层“全文”
        chapters = [ChapterPlan(title=_tidy(fallback_title, "全文"), page_start=1, page_end=page_count, order=1)]
        prev_start = 1
        for i, t in enumerate(ordered, start=1):
            nxt = ordered[i].page if i < len(ordered) else page_count + 1
            chapters[0].sections.append(
                SectionPlan(
                    title=_tidy(t.title, f"第{i}节"),
                    page_start=max(t.page, prev_start),
                    page_end=max(t.page, nxt - 1),
                    order=i,
                )
            )
            prev_start = t.page
        return chapters

    if not ordered:
        # 完全没结构：先按篇幅切块，等 M2 的 AI 归并
        chunk = max(10, min(30, page_count // 10 or 10))
        chapter = ChapterPlan(title=fallback_title, page_start=1, page_end=page_count, order=1)
        idx = 1
        for start in range(1, page_count + 1, chunk):
            end = min(page_count, start + chunk - 1)
            chapter.sections.append(SectionPlan(title=f"第 {idx} 部分（待 AI 归纳）", page_start=start, page_end=end, order=idx))
            idx += 1
        return [chapter]

    # 有章级标题：把节挂到各自章下
    chapter_starts = [t for t in ordered if t.level == 1]
    chapters: list[ChapterPlan] = []
    for i, t in enumerate(chapter_starts):
        nxt = chapter_starts[i + 1].page if i + 1 < len(chapter_starts) else page_count + 1
        chapters.append(
            ChapterPlan(
                title=_tidy(t.title, f"第{i + 1}章"),
                page_start=max(1, t.page),
                page_end=max(1, min(page_count, nxt - 1)),
                order=i + 1,
            )
        )

    # 第一个章之前若有节，补一个“前言”章
    first_chapter_page = chapter_starts[0].page
    if any(t.level == 2 and t.page < first_chapter_page for t in ordered):
        chapters.insert(
            0,
            ChapterPlan(title="前言", page_start=1, page_end=max(1, first_chapter_page - 1), order=0),
        )
        for c in chapters:
            c.order += 1

    def chapter_for(page_no: int) -> ChapterPlan:
        target = chapters[0]
        for c in chapters:
            if c.page_start <= page_no:
                target = c
        return target

    sections = [t for t in ordered if t.level == 2]
    for i, t in enumerate(sections):
        nxt = sections[i + 1].page if i + 1 < len(sections) else page_count + 1
        # 下一个章开始也要截断本节
        nxt_chapter = next((c.page_start for c in chapters if c.page_start > t.page), page_count + 1)
        end = max(t.page, min(nxt - 1, nxt_chapter - 1, page_count))
        ch = chapter_for(t.page)
        ch.sections.append(
            SectionPlan(
                title=_tidy(t.title, f"第{len(ch.sections) + 1}节"),
                page_start=max(ch.page_start, t.page),
                page_end=end,
                order=len(ch.sections) + 1,
            )
        )

    for c in chapters:
        if not c.sections:
            c.sections.append(SectionPlan(title="本章内容", page_start=c.page_start, page_end=c.page_end, order=1))

    chapters.sort(key=lambda c: (c.page_start, c.order))
    for i, c in enumerate(chapters, start=1):
        c.order = i
        for j, s in enumerate(c.sections, start=1):
            s.order = j
        if c.page_end < c.page_start:
            c.page_end = c.page_start
    return chapters
