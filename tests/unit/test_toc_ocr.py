"""目录行解析的跨平台回归：Windows / Linux 的 OCR 切词形态不同，但都应解析出同一批章节。"""
from __future__ import annotations

from app.pipeline.extract.ocr import OcrLine
from app.pipeline.outline.toc_ocr import parse_toc_rows


def _line(text: str, x: float, y: float, h: float = 28.0) -> OcrLine:
    return OcrLine(text=text, x=x, y=y, conf=0.98, h=h)


def _sections(rows):
    return [(r.section[0], r.section[1], r.section[2]) for r in rows if r.section]


W = 1310.0


def test_section_number_glued_to_title():
    """Linux OCR 常把编号和标题连成一串，不能吃掉标题前几个字。"""
    rows = parse_toc_rows(
        [_line("1.3药用植物资源的生态产业集成", 235, 604), _line("(8)", 1167, 604)],
        page_width=W,
    )
    assert _sections(rows) == [(1, 3, "药用植物资源的生态产业集成")]


def test_section_number_with_noise_separator_and_split_title():
    """Windows OCR 会出现 "2.1#" 这种尾随符号，标题另起一格。"""
    rows = parse_toc_rows(
        [_line("2.1#", 237, 728, 24), _line("植物资源学概述·", 301, 727, 27), _line("(11)", 1153, 724)],
        page_width=W,
    )
    assert _sections(rows) == [(2, 1, "植物资源学概述")]


def test_section_number_split_into_two_tokens():
    rows = parse_toc_rows(
        [_line("1.", 236, 447), _line("1", 268, 447), _line("药用植物资源产业化现状", 307, 448), _line("(2)", 1168, 447)],
        page_width=W,
    )
    assert _sections(rows) == [(1, 1, "药用植物资源产业化现状")]


def test_chapter_number_split_from_heading():
    rows = parse_toc_rows(
        [_line("2", 185, 689, 22), _line("药用植物资源·", 223, 686), _line("(11)", 1153, 684)],
        page_width=W,
    )
    chapters = [(r.chapter[0], r.chapter[1]) for r in rows if r.chapter]
    assert chapters == [(2, "药用植物资源")]
