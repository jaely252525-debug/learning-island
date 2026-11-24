"""多资料大纲合并的本地兜底实现。

真实模型走 `merge_outline.md`；这里用标题归一化 + 相似度聚类，保证没配
API Key 时也能把多份 PPT 合成一份可用大纲。模型输出不合法时同样回退到这里。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher


def _norm(title: str) -> str:
    text = (title or "").strip().lower()
    text = re.sub(r"^第\s*[一二三四五六七八九十百零〇0-9]+\s*[章节篇]\s*", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*\s*[.、]?\s*", "", text)
    text = re.sub(r"[\s\-—_·,，。；;：:、（）()【】\[\]《》<>/\\|]+", "", text)
    return text


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class _SectionBucket:
    title: str
    norm: str
    refs: list[dict] = field(default_factory=list)


@dataclass
class _ChapterBucket:
    title: str
    norm: str
    sections: list[_SectionBucket] = field(default_factory=list)


def _find_bucket(buckets, title: str, norm: str, threshold: float):
    for bucket in buckets:
        if _ratio(norm, bucket.norm) >= threshold:
            return bucket
    return None


def _ref(source_id: str, start, end) -> dict | None:
    try:
        start_i, end_i = int(start), int(end)
    except (TypeError, ValueError):
        return None
    if start_i > end_i:
        start_i, end_i = end_i, start_i
    if start_i < 1:
        start_i = 1
    if end_i < start_i:
        end_i = start_i
    return {"sourceId": source_id, "pageStart": start_i, "pageEnd": end_i}


def merge_outline_sources(sources: list[dict]) -> dict:
    """sources: [{sourceId, title, pageCount, chapters:[{title, sections:[{title,pageStart,pageEnd}]}]}]"""
    chapters: list[_ChapterBucket] = []
    for source in sources:
        source_id = str(source.get("sourceId") or "")
        source_chapters = source.get("chapters") or []
        if not source_chapters:
            source_chapters = [
                {
                    "title": "全文",
                    "sections": [
                        {"title": "全部内容", "pageStart": 1, "pageEnd": int(source.get("pageCount") or 1)}
                    ],
                }
            ]
        for chapter in source_chapters:
            chapter_title = str(chapter.get("title") or "综合资料")[:120]
            chapter_norm = _norm(chapter_title)
            chapter_bucket = _find_bucket(chapters, chapter_title, chapter_norm, 0.72)
            if chapter_bucket is None:
                chapter_bucket = _ChapterBucket(title=chapter_title, norm=chapter_norm)
                chapters.append(chapter_bucket)
            for section in chapter.get("sections") or []:
                section_title = str(section.get("title") or "本节内容")[:120]
                section_norm = _norm(section_title)
                section_bucket = _find_bucket(chapter_bucket.sections, section_title, section_norm, 0.72)
                if section_bucket is None:
                    section_bucket = _SectionBucket(title=section_title, norm=section_norm)
                    chapter_bucket.sections.append(section_bucket)
                ref = _ref(source_id, section.get("pageStart"), section.get("pageEnd"))
                if ref and all(
                    (r["sourceId"], r["pageStart"], r["pageEnd"])
                    != (ref["sourceId"], ref["pageStart"], ref["pageEnd"])
                    for r in section_bucket.refs
                ):
                    section_bucket.refs.append(ref)

    out_chapters: list[dict] = []
    for chapter in chapters:
        if not chapter.sections:
            continue
        title = chapter.title
        if len(chapters) == 1 and _norm(title) in {"全文", "未识别目录", "综合资料"}:
            title = "综合资料"
        sections = []
        for section in chapter.sections:
            if not section.refs:
                continue
            sections.append(
                {
                    "title": section.title,
                    "refs": section.refs[:8],
                }
            )
        if sections:
            out_chapters.append({"title": title[:120], "sections": sections[:40]})

    if not out_chapters:
        # 一页都没有结构时，至少把每份资料整本放进一个“全部内容”节
        refs = [
            _ref(str(s.get("sourceId") or ""), 1, int(s.get("pageCount") or 1))
            for s in sources
        ]
        refs = [r for r in refs if r]
        out_chapters = [{"title": "综合资料", "sections": [{"title": "全部内容", "refs": refs[:8]}]}]

    course_title = str((sources[0] if sources else {}).get("courseTitle") or "多资料合集")[:120]
    return {"title": course_title, "chapters": out_chapters[:20]}
