"""PDF 解析：有文字层优先用文字层；扫描版走「目录页 OCR + 页码偏移」，正文按需 OCR。"""
from __future__ import annotations

from collections import Counter

import pymupdf

from ...config import settings
from ..outline.page_offset import pick_offset
from ..outline.toc_ocr import rows_to_teeth, parse_toc_rows, summarise, dedupe
from .common import ExtractResult, PageData, Tooth, clean_text, classify_heading, detect_printed_number
from .ocr import get_engine


def _text_layer_probe(pdf: pymupdf.Document, limit: int = 12) -> int:
    """统计前若干页里有文字的页数。"""
    n = 0
    for i in range(min(pdf.page_count, limit)):
        if len((pdf.load_page(i).get_text("text") or "").strip()) >= 40:
            n += 1
    return n


def _detect_toc_pages(pdf_path: str, doc_id: str, page_count: int) -> tuple[list[int], list]:
    """在书前部探测目录页：命中「目录」关键词或连续出现 3 行以上章节条目的页面。"""
    engine = get_engine()
    probe_to = min(page_count, settings.toc_probe_to)
    hits: list[tuple[int, int, bool]] = []
    for pno in range(settings.toc_probe_from, probe_to + 1):
        width, _ = engine.page_size(pdf_path, pno, doc_id, dpi=settings.ocr_probe_dpi)
        lines = engine.ocr_page(pdf_path, pno, doc_id, dpi=settings.ocr_probe_dpi)
        if not lines:
            hits.append((pno, 0, False))
            continue
        rows = parse_toc_rows(lines, page_width=width)
        count = sum(
            1
            for r in rows
            if (r.chapter and r.chapter[2]) or (r.section and r.section[3])
        )
        is_toc_title = any(l.text.strip().startswith("目录") or "目次" in l.text for l in lines[:4])
        hits.append((pno, count, is_toc_title))

    anchor = None
    for pno, count, is_title in hits:
        if is_title and count >= 2:
            anchor = pno
            break
    if anchor is None:
        best = max(hits, key=lambda h: h[1], default=(0, 0, False))
        anchor = best[0] if best[1] >= 3 else None

    if anchor is None:
        return [], []
    toc_pages = [anchor]
    # 往后延：后续页仍有大量章节条目才算目录
    for pno, count, _ in [h for h in hits if h[0] > anchor]:
        if count >= 2:
            toc_pages.append(pno)
        else:
            break
    # 往前延：目录页常跨多页，前页若也是密集条目则并入
    for pno, count, _ in reversed([h for h in hits if h[0] < anchor]):
        if count >= 2:
            toc_pages.insert(0, pno)
        else:
            break
    return toc_pages, hits


def _scan_toc(pdf_path: str, doc_id: str, page_count: int) -> tuple[list[Tooth], int, dict, list[str]]:
    """扫描版：OCR 目录页，得到章/节与印刷页；偏移按「目录结束页之后即正文首页」推定并回验。"""
    engine = get_engine()
    warnings: list[str] = []
    toc_pages, probe = _detect_toc_pages(pdf_path, doc_id, page_count)
    if not toc_pages:
        warnings.append("未能定位目录页，骨架需要人工或 AI 归纳")
        return [], 0, {"tocPages": [], "probe": probe}, warnings

    rows = []
    for pno in toc_pages:
        width, _ = engine.page_size(pdf_path, pno, doc_id, dpi=settings.ocr_dpi)
        lines = engine.ocr_page(pdf_path, pno, doc_id, dpi=settings.ocr_dpi)
        rows.extend(parse_toc_rows(lines, page_width=width))

    deduped = dedupe(rows)

    offset = toc_pages[-1]  # 印刷页 1 = 目录结束后的第一页（示例书：目录到 p10 → 偏移 10）
    # 回验：正文首页上找印刷页码
    try:
        lines = engine.ocr_page(pdf_path, min(page_count, offset + 1), doc_id, dpi=settings.ocr_probe_dpi)
        max_y = max((l.y for l in lines), default=1)
        for line in lines:
            if line.y >= max_y * 0.8:
                m = detect_printed_number(line.text)
                if m and m <= 3:
                    offset = offset + 1 - m
                    break
    except Exception:  # noqa: BLE001
        warnings.append("正文首页回验失败，页码偏移按目录页位置推定")

    stats = summarise(deduped)
    stats["tocPages"] = toc_pages
    stats["pageOffset"] = offset
    if stats["chapters"] == 0:
        warnings.append("目录里没识别出章级条目")
    if stats["lowConfidenceRows"]:
        warnings.append(f"{stats['lowConfidenceRows']} 行 OCR 置信度偏低，建议抽查")
    return rows_to_teeth(deduped, offset), offset, stats, warnings


def extract_pdf(path: str, doc_id: str) -> ExtractResult:
    pdf = pymupdf.open(path)
    try:
        page_total = pdf.page_count
        scanned = min(page_total, settings.max_pages)
        warnings: list[str] = []
        if page_total > settings.max_pages:
            warnings.append(f"页数 {page_total} 超过上限 {settings.max_pages}，只处理前 {settings.max_pages} 页")

        text_probe = _text_layer_probe(pdf)
        has_text_layer = text_probe > 0
        pages: list[PageData] = []
        teeth: list[Tooth] = []
        offset = 0

        if not has_text_layer:
            teeth, offset, stats, ocr_warnings = _scan_toc(path, doc_id, page_total)
            warnings.extend(ocr_warnings)
            warnings.append("扫描版：正文按需 OCR（生成到哪节，识别哪几页）")
            for i in range(scanned):
                pages.append(PageData(page_no=i + 1, printed_page=None, text="", char_count=0))
            for p in pages:
                p.printed_page = p.page_no - offset if p.page_no - offset >= 1 else None
            return ExtractResult(
                page_count=page_total,
                pages=pages,
                teeth=teeth,
                page_offset=offset,
                has_text_layer=False,
                method="pdf_scan_toc_ocr",
                warnings=warnings,
                stats=stats,
            )

        votes: Counter[int] = Counter()
        toc = pdf.get_toc(simple=True) or []
        for i in range(scanned):
            page = pdf.load_page(i)
            text = clean_text(page.get_text("text") or "")
            printed = detect_printed_number(text)
            if printed is not None:
                votes[(i + 1) - printed] += 1
            pages.append(
                PageData(page_no=i + 1, printed_page=None, text=text, char_count=len(text))
            )

        offset = pick_offset(votes)
        for p in pages:
            p.printed_page = p.page_no - offset if p.page_no - offset >= 1 else None

        if toc:
            for order, item in enumerate(toc):
                lvl, title, pno = item[0], str(item[1]).strip(), int(item[2])
                if lvl <= 2 and 0 < pno <= page_total:
                    teeth.append(Tooth(level=1 if lvl == 1 else 2, title=title, page=pno, order=order))
        else:
            for p in pages:
                if len(teeth) > 120:
                    break
                hits = 0
                for line in p.text.split("\n")[:12]:
                    got = classify_heading(line)
                    if got and hits < 2:
                        teeth.append(Tooth(level=got[0], title=got[1], page=p.page_no, order=len(teeth)))
                        hits += 1

        # 书签只有页码、没有标题时（很多扫描书都这样），回退到正文标题行
        if teeth and all(str(t.title).strip().isdigit() for t in teeth):
            warnings.append("PDF 书签只有页码没有标题，已改用正文标题识别")
            teeth = []
            for p in pages:
                if len(teeth) > 120:
                    break
                hits = 0
                for line in p.text.split("\n")[:12]:
                    got = classify_heading(line)
                    if got and hits < 2:
                        teeth.append(Tooth(level=got[0], title=got[1], page=p.page_no, order=len(teeth)))
                        hits += 1

        method = "pdf_bookmarks" if toc and teeth else ("pdf_headings" if teeth else "pdf_fallback")
        return ExtractResult(
            page_count=page_total,
            pages=pages,
            teeth=teeth,
            page_offset=offset,
            has_text_layer=True,
            method=method,
            warnings=warnings,
        )
    finally:
        pdf.close()
