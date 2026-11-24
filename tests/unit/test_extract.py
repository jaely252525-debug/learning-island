"""解析器单测：PDF 书签 / DOCX 无标题 / PPTX / PPT 富内容。"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from app.pipeline.extract import extract


def test_pdf_bookmarks_and_offset(fixtures_dir: Path):
    res = extract(str(fixtures_dir / "book.pdf"), "doc_test")
    assert res.page_count == 12
    assert res.method == "pdf_bookmarks"
    assert len(res.teeth) == 6
    assert res.teeth[0].level == 1 and res.teeth[0].page == 3
    # 印刷页 1 = PDF 第 3 页 → 偏移 2
    assert res.page_offset == 2
    assert res.pages[2].printed_page == 1
    assert res.has_text_layer is True
    assert "超临界流体萃取" in res.pages[5].text


def test_docx_without_headings(fixtures_dir: Path):
    res = extract(str(fixtures_dir / "notes.docx"), "doc_test")
    assert res.page_count >= 1
    assert res.teeth == []
    assert any("无标题样式" in w for w in res.warnings)


def test_pptx_titles(fixtures_dir: Path):
    res = extract(str(fixtures_dir / "slides.pptx"), "doc_test")
    assert res.page_count == 6
    assert len(res.teeth) == 6
    assert all(t.level == 2 for t in res.teeth)


def test_pptx_tables_charts_images_notes(tmp_path: Path):
    path = tmp_path / "rich.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "图表与表格"
    body = slide.shapes.add_textbox(Inches(0.5), Inches(1.3), Inches(4), Inches(0.7))
    body.text_frame.text = "正文要点：提取温度与时间"

    table = slide.shapes.add_table(3, 2, Inches(0.5), Inches(2.1), Inches(4.2), Inches(1.1)).table
    table.cell(0, 0).text = "方法"
    table.cell(0, 1).text = "温度"
    table.cell(1, 0).text = "水提"
    table.cell(1, 1).text = "100 °C"
    table.cell(2, 0).text = "超临界"
    table.cell(2, 1).text = "31.1 °C"

    chart_data = CategoryChartData()
    chart_data.categories = ["2023", "2024"]
    chart_data.add_series("得率", (12.5, 18.2))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(3.5), Inches(4.2), Inches(2.5), chart_data
    ).chart
    chart.has_title = True
    chart.chart_title.text_frame.text = "年度得率"

    image = Image.new("RGB", (800, 240), "white")
    ImageDraw.Draw(image).text((40, 90), "SPECIAL-OCR-7788", fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    slide.shapes.add_picture(BytesIO(buffer.getvalue()), Inches(5), Inches(1.0), width=Inches(3))

    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(5), Inches(3), Inches(2.5), Inches(0.6)).text_frame.text = "组合形状文字：超声辅助"
    slide.notes_slide.notes_text_frame.text = "这里常考图表读数，注意 31.1 摄氏度。"
    prs.save(path)

    res = extract(str(path), "doc_test")
    text = res.pages[0].text
    assert "正文要点：提取温度与时间" in text
    assert "| 水提 | 100 °C |" in text
    assert "类别：2023、2024" in text
    assert "系列「得率」：12.5、18.2" in text
    assert "OCR-7788" in text
    assert "组合形状文字：超声辅助" in text
    assert "这里常考图表读数" in text
    assert res.stats["tables"] == 1
    assert res.stats["charts"] == 1
    assert res.stats["pictures"] == 1
    assert res.stats["picturesOcr"] == 1
    assert res.stats["notes"] == 1
    assert res.pages[0].ocr_confidence and res.pages[0].ocr_confidence > 0.5


def test_markdown_headings(fixtures_dir: Path):
    res = extract(str(fixtures_dir / "note.md"), "doc_test")
    assert [t.level for t in res.teeth] == [1, 2, 2]
