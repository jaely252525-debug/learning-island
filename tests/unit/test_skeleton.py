"""骨架构建与页码偏移的单测。"""
from __future__ import annotations

from collections import Counter

from app.pipeline.extract.common import Tooth, classify_heading, detect_printed_number
from app.pipeline.outline.build import build_skeleton, pick_offset


def test_chapters_and_sections():
    teeth = [
        Tooth(1, "第一章 总论", 3, 0),
        Tooth(2, "1.1 传统提取", 3, 1),
        Tooth(2, "1.2 超临界", 6, 2),
        Tooth(1, "第二章 工艺", 8, 3),
        Tooth(2, "2.1 超声", 8, 4),
    ]
    chapters = build_skeleton(teeth, 10)
    assert [c.title for c in chapters] == ["第一章 总论", "第二章 工艺"]
    assert chapters[0].page_start == 3 and chapters[0].page_end == 7
    assert len(chapters[0].sections) == 2
    assert chapters[0].sections[0].page_end == 5
    assert chapters[1].page_end == 10
    assert len(chapters[1].sections) == 1


def test_only_sections_get_a_wrapper_chapter():
    teeth = [Tooth(2, "绪论", 1, 0), Tooth(2, "方法", 5, 1), Tooth(2, "结论", 8, 2)]
    chapters = build_skeleton(teeth, 10, fallback_title="讲义")
    assert len(chapters) == 1
    assert chapters[0].title == "讲义"
    assert [s.title for s in chapters[0].sections] == ["绪论", "方法", "结论"]


def test_no_teeth_falls_back_to_chunks():
    chapters = build_skeleton([], 45)
    assert len(chapters) == 1
    assert chapters[0].page_start == 1 and chapters[0].page_end == 45
    assert len(chapters[0].sections) >= 1


def test_empty_chapter_gets_placeholder_section():
    teeth = [Tooth(1, "第一章", 1, 0), Tooth(1, "第二章", 4, 1)]
    chapters = build_skeleton(teeth, 6)
    assert chapters[0].sections[0].title == "本章内容"


def test_pick_offset_prefers_most_votes():
    votes: Counter[int] = Counter({10: 5, 11: 2, 0: 1})
    assert pick_offset(votes) == 10
    assert pick_offset(Counter({0: 1})) == 0


def test_classify_heading():
    assert classify_heading("第一章 总论") == (1, "第一章 总论")
    assert classify_heading("第3节 实验方法") == (2, "第3节 实验方法")
    assert classify_heading("1.2 超临界流体萃取") == (2, "1.2 超临界流体萃取")
    assert classify_heading("这是一句普通正文，长度超过限制的时候就不该被当成标题了，所以这里多写一些字。") is None


def test_detect_printed_number():
    assert detect_printed_number("正文\n\n12") == 12
    assert detect_printed_number("第 7 页\n正文") == 7
    assert detect_printed_number("正文里提到 2020 年的数据") is None
