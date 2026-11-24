"""DOCX / PPTX 解析：用 Word 的 Heading 样式和 PPT 的标题占位符当骨架。

PPT 不只读文本框：表格、原生图表、图片 OCR、组合形状、SmartArt 文字和
演讲者备注都会抽出来，按“块”写进同一页文本，方便后续出处回查。
"""
from __future__ import annotations

from io import BytesIO

from docx import Document as DocxDocument
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from .common import ExtractResult, PageData, Tooth, clean_text, classify_heading

CHARS_PER_PAGE = 1200  # Office 文档没有真实分页，按字符量估算页码


def _docx_paragraph_text(p) -> str:
    return clean_text(p.text or "")


def extract_docx(path: str) -> ExtractResult:
    doc = DocxDocument(path)
    teeth: list[Tooth] = []
    pages: list[dict] = []
    buf: list[str] = []
    char_cursor = 0
    page_no = 1
    warnings: list[str] = []
    heading_count = 0

    for p in doc.paragraphs:
        text = _docx_paragraph_text(p)
        if not text:
            continue
        style = (p.style.name or "") if p.style is not None else ""
        level = None
        if style.startswith("Heading") or style.startswith("标题"):
            digit = "".join(ch for ch in style if ch.isdigit())
            lvl = int(digit) if digit else 1
            level = 1 if lvl == 1 else 2
        if level is None:
            got = classify_heading(text)
            if got and len(text) <= 40:
                level, heading_text = got
            else:
                heading_text = ""
        else:
            heading_text = text
        if level is not None:
            heading_count += 1
            char_cursor += len(heading_text)
            teeth.append(Tooth(level=level, title=heading_text, page=max(1, char_cursor // CHARS_PER_PAGE + 1), order=len(teeth)))

        buf.append(text)
        char_cursor += len(text)
        est_page = char_cursor // CHARS_PER_PAGE + 1
        if est_page != page_no:
            pages.append({"page_no": page_no, "text": "\n".join(buf)})
            buf = []
            page_no = est_page
    if buf:
        pages.append({"page_no": page_no, "text": "\n".join(buf)})
    if not pages:
        pages.append({"page_no": 1, "text": ""})

    if heading_count == 0:
        warnings.append("DOCX 无标题样式，骨架需 AI 归纳（M2）或按篇幅切分")

    out_pages = [
        PageData(page_no=p["page_no"], printed_page=p["page_no"], text=p["text"], char_count=len(p["text"]) if False else len(p["text"]))
        for p in pages
    ]
    for p in out_pages:
        p.char_count = len(p.text)

    return ExtractResult(
        page_count=len(out_pages),
        pages=out_pages,
        teeth=teeth,
        page_offset=0,
        has_text_layer=True,
        method="docx_headings" if heading_count else "docx_fallback",
        warnings=warnings + ["页码为按字数估算"],
    )


PPT_OCR_MIN_CONF = 0.35
PPT_MIN_IMAGE_EMU = 457200  # 小于 0.5 英寸的图标不 OCR，避免装饰元素产生乱码
PPT_MAX_OCR_IMAGES_PER_SLIDE = 12
PPT_MAX_CHART_CATEGORIES = 30
PPT_MAX_CHART_SERIES = 12


def _warn_once(warnings: list[str], message: str, marker: str, limit: int = 5) -> None:
    if sum(marker in w for w in warnings) < limit:
        warnings.append(message)


def _text_frame_block(text_frame) -> str:
    """保留段落层级；比直接 text_frame.text 更适合大纲识别。"""
    lines: list[str] = []
    for p in text_frame.paragraphs:
        text = clean_text(p.text or "")
        if text:
            lines.append(("  " * min(getattr(p, "level", 0) or 0, 6)) + text)
    return "\n".join(lines)


def _cell_text(cell) -> str:
    text = clean_text(getattr(cell, "text", "") or "")
    return text.replace("|", "\\|").replace("\n", " ")


def _table_block(table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([_cell_text(cell) for cell in row.cells])
    if not any(any(cell for cell in row) for row in rows):
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "[表格]\n" + "\n".join(lines) + "\n[/表格]"


def _chart_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _chart_block(chart) -> str:
    lines = [f"[图表] {chart.chart_type}"]
    try:
        if chart.has_title and chart.chart_title.has_text_frame:
            title = clean_text(chart.chart_title.text_frame.text)
            if title:
                lines.append(f"标题：{title}")
    except Exception:
        pass

    plotted = 0
    try:
        plots = list(chart.plots)
    except Exception:
        plots = []
    for plot in plots:
        try:
            categories = list(plot.categories or [])
        except Exception:
            categories = []
        if categories:
            shown = categories[:PPT_MAX_CHART_CATEGORIES]
            suffix = "…" if len(categories) > len(shown) else ""
            lines.append("类别：" + "、".join(_chart_value(c) for c in shown) + suffix)
        try:
            series_list = list(plot.series)
        except Exception:
            series_list = []
        for series in series_list[:PPT_MAX_CHART_SERIES]:
            try:
                values = list(series.values or [])
            except Exception:
                values = []
            if not values:
                continue
            name = clean_text(str(series.name or "系列"))
            shown = values[:PPT_MAX_CHART_CATEGORIES]
            suffix = "…" if len(values) > len(shown) else ""
            lines.append(f"系列「{name}」：" + "、".join(_chart_value(v) for v in shown) + suffix)
            plotted += 1
    if not plotted:
        lines.append("（图表没有缓存数值，可能需要视觉模型辅助读取）")
    return "\n".join(lines) + "\n[/图表]"


def _ocr_picture(shape, slide_no: int, stats: dict, warnings: list[str]) -> str:
    if not hasattr(shape, "image"):
        return ""
    width = int(getattr(shape, "width", 0) or 0)
    height = int(getattr(shape, "height", 0) or 0)
    if min(width, height) < PPT_MIN_IMAGE_EMU:
        stats["picturesSkipped"] = stats.get("picturesSkipped", 0) + 1
        return ""
    if stats.get("picturesTriedThisSlide", 0) >= PPT_MAX_OCR_IMAGES_PER_SLIDE:
        stats["picturesSkipped"] = stats.get("picturesSkipped", 0) + 1
        return ""
    stats["picturesTriedThisSlide"] = stats.get("picturesTriedThisSlide", 0) + 1
    try:
        blob = shape.image.blob
        ext = (shape.image.ext or "").lower()
    except Exception as exc:
        _warn_once(warnings, f"第{slide_no}页图片读取失败：{exc}", "图片读取失败")
        return ""
    if ext in {"wmf", "emf", "svg"}:
        _warn_once(warnings, f"第{slide_no}页有 {ext} 矢量图，暂不做 OCR", "矢量图")
        return ""

    try:
        from PIL import Image

        image = Image.open(BytesIO(blob))
        if image.mode in {"RGBA", "LA", "P"}:
            image = image.convert("RGBA")
            canvas = Image.new("RGB", image.size, (255, 255, 255))
            canvas.paste(image, mask=image.getchannel("A"))
            image = canvas
        else:
            image = image.convert("RGB")
        if max(image.size) > 2400:
            image.thumbnail((2400, 2400))

        import numpy as np

        from .ocr import get_engine

        lines = get_engine().ocr_image(np.asarray(image))
    except Exception as exc:
        _warn_once(warnings, f"第{slide_no}页图片 OCR 失败：{exc}", "图片 OCR 失败")
        return ""

    kept = [line for line in lines if line.text.strip() and line.conf >= PPT_OCR_MIN_CONF]
    if not kept:
        stats["picturesEmpty"] = stats.get("picturesEmpty", 0) + 1
        return ""
    stats["picturesOcrThisSlide"] = stats.get("picturesOcrThisSlide", 0) + 1
    stats["picturesOcr"] = stats.get("picturesOcr", 0) + 1
    if stats["picturesOcrThisSlide"] == 1:
        stats["ocrPages"] = stats.get("ocrPages", 0) + 1
    kept.sort(key=lambda line: (round(line.y / 12), line.x))
    conf = sum(line.conf for line in kept) / len(kept)
    stats["ocrLines"] = stats.get("ocrLines", 0) + len(kept)
    stats["ocrConfidenceSum"] = stats.get("ocrConfidenceSum", 0.0) + conf
    stats["ocrConfidenceThisSlide"] = stats.get("ocrConfidenceThisSlide", 0.0) + conf
    if conf < 0.7:
        stats["lowConfidenceOcr"] = stats.get("lowConfidenceOcr", 0) + 1
    text = "\n".join(line.text.strip() for line in kept)
    return f"[图片OCR 置信度 {conf:.2f}]\n{text}\n[/图片OCR]"


def _xml_text_block(shape) -> str:
    """SmartArt / 图示等没有 text_frame 的形状，直接抓 DrawingML 的 a:t。"""
    try:
        nodes = shape._element.findall(".//" + qn("a:t"))
    except Exception:
        return ""
    texts = [clean_text(node.text or "") for node in nodes]
    texts = [text for text in texts if text]
    return "\n".join(texts)


def _shape_blocks(shape, slide_no: int, stats: dict, warnings: list[str], depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    if getattr(shape, "has_table", False):
        block = _table_block(shape.table)
        if block:
            stats["tables"] = stats.get("tables", 0) + 1
            return [block]
        return []
    if getattr(shape, "has_chart", False):
        stats["charts"] = stats.get("charts", 0) + 1
        return [_chart_block(shape.chart)]
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        blocks: list[str] = []
        for child in shape.shapes:
            blocks.extend(_shape_blocks(child, slide_no, stats, warnings, depth + 1))
        return blocks
    if getattr(shape, "has_text_frame", False):
        block = _text_frame_block(shape.text_frame)
        if block:
            stats["textBlocks"] = stats.get("textBlocks", 0) + 1
        return [block] if block else []
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image"):
        stats["pictures"] = stats.get("pictures", 0) + 1
        block = _ocr_picture(shape, slide_no, stats, warnings)
        return [block] if block else []
    block = _xml_text_block(shape)
    if block:
        stats["textBlocks"] = stats.get("textBlocks", 0) + 1
    return [block] if block else []


def _slide_notes(slide) -> str:
    try:
        if not slide.has_notes_slide:
            return ""
        return clean_text(slide.notes_slide.notes_text_frame.text or "")
    except Exception:
        return ""


def extract_pptx(path: str) -> ExtractResult:
    prs = Presentation(path)
    pages: list[PageData] = []
    teeth: list[Tooth] = []
    warnings: list[str] = ["页码按幻灯片序号，非印刷页", "PPT 图表与图片为自动解析，复杂图示建议抽查原文"]
    stats: dict = {
        "slides": 0,
        "textBlocks": 0,
        "tables": 0,
        "charts": 0,
        "pictures": 0,
        "picturesOcr": 0,
        "picturesSkipped": 0,
        "picturesEmpty": 0,
        "notes": 0,
    }

    for idx, slide in enumerate(prs.slides, start=1):
        stats["slides"] += 1
        stats["picturesOcrThisSlide"] = 0
        stats["picturesTriedThisSlide"] = 0
        stats["ocrConfidenceThisSlide"] = 0.0
        title = ""
        title_shape = None
        try:
            title_shape = slide.shapes.title
            if title_shape is not None and title_shape.has_text_frame:
                title = clean_text(title_shape.text_frame.text)
        except Exception:
            title = ""

        blocks: list[str] = []
        if title:
            blocks.append(f"【标题】{title}")
        title_id = getattr(title_shape, "shape_id", None)
        for shape in slide.shapes:
            if title_id is not None and getattr(shape, "shape_id", None) == title_id:
                continue
            blocks.extend(_shape_blocks(shape, idx, stats, warnings))

        notes = _slide_notes(slide)
        if notes:
            stats["notes"] += 1
            blocks.append(f"[备注]\n{notes}\n[/备注]")

        body = "\n\n".join(block for block in blocks if block.strip())
        page_conf = None
        if stats.get("picturesOcrThisSlide", 0):
            page_conf = round(
                stats.get("ocrConfidenceThisSlide", 0.0) / stats["picturesOcrThisSlide"],
                3,
            )
        pages.append(
            PageData(
                page_no=idx,
                printed_page=idx,
                text=body,
                char_count=len(body),
                ocr_confidence=page_conf,
            )
        )

        label = title
        if not label:
            for block in blocks:
                if block.startswith(("【标题】", "[表格]", "[图表]", "[图片OCR", "[备注]")):
                    continue
                first_line = block.split("\n")[0].strip()
                if first_line:
                    label = first_line[:40]
                    break
        label = label or f"第{idx}页"
        got = classify_heading(label)
        if got and got[0] == 1:
            teeth.append(Tooth(level=1, title=label, page=idx, order=len(teeth)))
        else:
            teeth.append(Tooth(level=2, title=label, page=idx, order=len(teeth)))

    if not teeth:
        warnings.append("PPTX 无标题，骨架需 AI 归纳（M2）")

    ocr_pages = stats.get("ocrPages", 0)
    if ocr_pages:
        stats["ocrMeanConfidence"] = round(
            stats.get("ocrConfidenceSum", 0.0) / max(1, stats.get("picturesOcr", 0)), 3
        )
        if stats.get("lowConfidenceOcr", 0):
            warnings.append(f"{stats['lowConfidenceOcr']} 张图片 OCR 置信度偏低，建议抽查")
    stats.pop("ocrConfidenceSum", None)
    stats.pop("picturesOcrThisSlide", None)
    stats.pop("picturesTriedThisSlide", None)
    stats.pop("ocrConfidenceThisSlide", None)

    return ExtractResult(
        page_count=len(pages),
        pages=pages,
        teeth=teeth,
        page_offset=0,
        has_text_layer=True,  # PPT 图片已在解析阶段 OCR，不再走 PDF 页 OCR
        method="pptx_titles" if teeth else "pptx_fallback",
        warnings=warnings,
        stats=stats,
    )
