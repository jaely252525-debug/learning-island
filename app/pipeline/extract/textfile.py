"""Markdown / TXT：按 # 层级或“第X章”切；TXT 无结构就按篇幅切片。"""
from __future__ import annotations

import re

from .common import ExtractResult, PageData, Tooth, clean_text, classify_heading

CHARS_PER_PAGE = 1500


def _read(path: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_markdown(path: str) -> ExtractResult:
    raw = clean_text(_read(path))
    teeth: list[Tooth] = []
    pages: list[PageData] = []
    page_no = 1
    buf: list[str] = []
    cursor = 0

    for line in raw.split("\n"):
        m = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
        if m:
            level = 1 if len(m.group(1)) == 1 else 2
            cursor += len(m.group(2))
            teeth.append(
                Tooth(
                    level=level,
                    title=m.group(2).strip()[:80],
                    page=max(1, cursor // CHARS_PER_PAGE + 1),
                    order=len(teeth),
                )
            )
            buf.append(line)
            continue
        got = classify_heading(line)
        if got and len(line.strip()) <= 40:
            cursor += len(line.strip())
            teeth.append(Tooth(level=got[0], title=got[1], page=max(1, cursor // CHARS_PER_PAGE + 1), order=len(teeth)))
        buf.append(line)
        cursor += len(line)
        est = cursor // CHARS_PER_PAGE + 1
        if est != page_no:
            body = "\n".join(buf)
            pages.append(PageData(page_no=page_no, printed_page=page_no, text=body, char_count=len(body)))
            buf, page_no = [], est
    if buf:
        body = "\n".join(buf)
        pages.append(PageData(page_no=page_no, printed_page=page_no, text=body, char_count=len(body)))

    return ExtractResult(
        page_count=len(pages),
        pages=pages,
        teeth=teeth,
        page_offset=0,
        has_text_layer=True,
        method="markdown_headings" if teeth else "text_fallback",
        warnings=["页码为按字数估算"],
    )


def extract_txt(path: str) -> ExtractResult:
    raw = clean_text(_read(path))
    teeth: list[Tooth] = []
    pages: list[PageData] = []
    page_no = 1
    buf: list[str] = []
    cursor = 0

    for line in raw.split("\n"):
        got = classify_heading(line)
        if got and len(line.strip()) <= 40:
            cursor += len(line.strip())
            teeth.append(Tooth(level=got[0], title=got[1], page=max(1, cursor // CHARS_PER_PAGE + 1), order=len(teeth)))
        buf.append(line)
        cursor += len(line)
        est = cursor // CHARS_PER_PAGE + 1
        if est != page_no:
            body = "\n".join(buf)
            pages.append(PageData(page_no=page_no, printed_page=page_no, text=body, char_count=len(body)))
            buf, page_no = [], est
    if buf:
        body = "\n".join(buf)
        pages.append(PageData(page_no=page_no, printed_page=page_no, text=body, char_count=len(body)))

    return ExtractResult(
        page_count=max(1, len(pages)),
        pages=pages,
        teeth=teeth,
        page_offset=0,
        has_text_layer=True,
        method="text_headings" if teeth else "text_fallback",
        warnings=["页码为按字数估算"] + ([] if teeth else ["未识别标题，骨架需 AI 归纳（M2）"]),
    )
