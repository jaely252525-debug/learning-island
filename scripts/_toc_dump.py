"""打印目录 OCR 解析出的章/节行（复用已缓存的页面图，很快）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.pipeline.extract.ocr import get_engine
from app.pipeline.outline.toc_ocr import dedupe, parse_toc_rows

PDF = os.environ.get("BOOK_PDF", "你的教材.pdf")
PAGES = [6, 7, 8, 9, 10, 11]

eng = get_engine()
rows = []
for p in PAGES:
    w, _ = eng.page_size(PDF, p, "probe", dpi=settings.ocr_dpi)
    lines = eng.ocr_page(PDF, p, "probe", dpi=settings.ocr_dpi)
    rows.extend(parse_toc_rows(lines, page_width=w))

for r in dedupe(rows):
    if r.chapter:
        print(f"[C] ch{r.chapter[0]} p={r.chapter[2]} y={r.y:.0f} {r.chapter[1]!r}")
    elif r.section:
        print(f"[S] {r.section[0]}.{r.section[1]} p={r.section[3]} y={r.y:.0f} {r.section[2]!r}")
