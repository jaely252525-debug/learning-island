"""解析层公共类型与文本清洗。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Tooth:
    """目录里的一根“齿”：level 1=章，2=节。"""

    level: int
    title: str
    page: int
    order: int = 0


@dataclass
class PageData:
    page_no: int
    printed_page: int | None
    text: str
    char_count: int = 0
    ocr_confidence: float | None = None
    image_key: str | None = None


@dataclass
class ExtractResult:
    page_count: int
    pages: list[PageData] = field(default_factory=list)
    teeth: list[Tooth] = field(default_factory=list)
    page_offset: int = 0
    has_text_layer: bool = True
    method: str = ""
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


_MULTI_BLANK = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t\u3000]+")


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES.sub(" ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return _MULTI_BLANK.sub("\n\n", text).strip()


_CHAPTER_RE = re.compile(r"^\s*第\s*([0-9一二三四五六七八九十百]+)\s*[章篇]\s*(.*)$")
_SECTION_RE = re.compile(r"^\s*第\s*([0-9一二三四五六七八九十百]+)\s*节\s*(.*)$")
_DECO_SECTION_RE = re.compile(r"^\s*([0-9]{1,2}(?:\.[0-9]{1,2}){0,3})[\.\s]\s*([^\s].{1,40})$")
_PAGE_NUM_RE = re.compile(r"^\s*[-—–·]?\s*(\d{1,4})\s*[-—–·]?\s*$")
_PAGE_CN_RE = re.compile(r"^\s*第\s*(\d{1,4})\s*页\s*$")


def detect_printed_number(text: str) -> int | None:
    """从页眉/页脚捞印刷页码：只看首尾各 3 行，避免误抓正文里的数字。"""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    for ln in lines[:3] + lines[-3:]:
        m = _PAGE_NUM_RE.match(ln.strip())
        if m:
            n = int(m.group(1))
            if 0 < n <= 2000:
                return n
        m = _PAGE_CN_RE.match(ln.strip())
        if m:
            return int(m.group(1))
    return None


def classify_heading(line: str) -> tuple[int, str] | None:
    """判断一行是不是标题，返回 (level, title)。"""
    s = line.strip()
    if not s or len(s) > 60:
        return None
    m = _CHAPTER_RE.match(s)
    if m:
        title = s if m.group(2).strip() else f"第{m.group(1)}章"
        return 1, title
    m = _SECTION_RE.match(s)
    if m:
        title = s if m.group(2).strip() else f"第{m.group(1)}节"
        return 2, title
    m = _DECO_SECTION_RE.match(s)
    if m:
        # 编号式标题（1.2 xxx），过短或多句的不算
        return 2, s
    return None
