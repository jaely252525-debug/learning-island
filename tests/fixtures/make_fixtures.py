"""生成测试用的最小样本文件（PDF 带书签 / DOCX 无标题 / PPTX）。"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from docx import Document as DocxDocument
from pptx import Presentation
from pptx.util import Inches, Pt

FIXTURES = Path(__file__).resolve().parent


def make_book_pdf(path: Path) -> None:
    """12 页：前 2 页封面/目录（无印刷页码），正文 10 页印刷页 1–10。"""
    pdf = pymupdf.open()
    pages: list[tuple[int, str]] = [
        (1, "药用植物过程工程及其生态产业集成\n封面"),
        (2, "目录\n第一章 总论 ...... 1\n第二章 工艺 ...... 6"),
    ]
    body = [
        ("第一章 总论", "本章介绍药用植物过程工程的基本概念、研究对象与产业背景。"),
        ("1.1 传统提取方法", "传统提取方法包括溶剂提取、水蒸气蒸馏与压榨法，操作简单但效率较低。"),
        ("1.1 传统提取方法（续）", "溶剂选择遵循相似相溶原则，常用乙醇、水与石油醚。"),
        ("1.2 超临界流体萃取", "超临界流体萃取利用超临界二氧化碳的溶解能力，适合热敏性成分。"),
        ("1.2 超临界流体萃取（续）", "临界温度 31.1 摄氏度，临界压力 7.38 兆帕，萃取后无溶剂残留。"),
        ("第二章 工艺", "第二章讨论工艺放大、设备选型与质量控制。"),
        ("2.1 超声辅助提取", "超声空化作用破坏细胞壁，缩短提取时间并提高得率。"),
        ("2.2 微波萃取技术", "微波体加热使细胞内水分汽化，压力升高导致细胞破裂。"),
        ("2.2 微波萃取技术（续）", "微波萃取适合含水量较高的物料，工业放大需考虑温度均匀性。"),
        ("小结", "综合比较四类提取技术在能耗、成本与产品品质上的差异。"),
    ]
    for page_no, text in pages:
        page = pdf.new_page()
        page.insert_text((72, 100), text, fontsize=12, fontname="china-s")
    for i, (title, body_text) in enumerate(body, start=1):
        page = pdf.new_page()
        page.insert_text((72, 90), title, fontsize=16, fontname="china-s")
        page.insert_text((72, 130), body_text, fontsize=11, fontname="china-s")
        page.insert_text((300, 800), str(i), fontsize=10, fontname="china-s")  # 页脚印刷页码
    pdf.set_toc(
        [
            [1, "第一章 总论", 3],
            [2, "1.1 传统提取方法", 3],
            [2, "1.2 超临界流体萃取", 6],
            [1, "第二章 工艺", 8],
            [2, "2.1 超声辅助提取", 8],
            [2, "2.2 微波萃取技术", 10],
        ]
    )
    pdf.save(str(path))
    pdf.close()


def make_docx_no_heading(path: Path) -> None:
    doc = DocxDocument()
    doc.add_paragraph("这是一份没有标题样式的讲义草稿。")
    for i in range(1, 61):
        doc.add_paragraph(f"第 {i} 段：植物有效成分的提取需要考虑溶剂、温度与时间三个因素。")
    doc.save(str(path))


def make_pptx_no_toc(path: Path) -> None:
    prs = Presentation()
    blank = prs.slide_layouts[1]
    titles = ["课程概览", "提取方法分类", "超临界流体萃取", "超声辅助提取", "微波萃取", "课堂练习"]
    for title in titles:
        slide = prs.slides.add_slide(blank)
        slide.shapes.title.text = title
        body = slide.placeholders[1]
        body.text = f"{title}：本页要点见讲义。"
        body.text_frame.paragraphs[0].font.size = Pt(16)
    prs.save(str(path))


def make_md(path: Path) -> None:
    path.write_text(
        "# 天然产物提取\n\n## 传统方法\n\n溶剂提取、水蒸气蒸馏。\n\n## 超临界萃取\n\n以 CO2 为溶剂。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    make_book_pdf(FIXTURES / "book.pdf")
    make_docx_no_heading(FIXTURES / "notes.docx")
    make_pptx_no_toc(FIXTURES / "slides.pptx")
    make_md(FIXTURES / "note.md")
    print("fixtures 已生成：", FIXTURES)

