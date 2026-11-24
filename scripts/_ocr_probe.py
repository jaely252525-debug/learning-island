"""探针：对教材 PDF 的若干页做 OCR，打印结果，用来设计目录解析规则。"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pymupdf
from rapidocr_onnxruntime import RapidOCR

PDF = os.environ.get("BOOK_PDF", "你的教材.pdf")


def main(pages: list[int], dpi: int = 200) -> None:
    engine = RapidOCR()
    doc = pymupdf.open(PDF)
    for pno in pages:
        page = doc[pno - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        t0 = time.time()
        result, _ = engine(img)
        print(f"===== PDF p{pno} 用时 {time.time() - t0:.1f}s =====")
        if not result:
            print("(no text)")
            continue
        for item in result:
            box, text = item[0], item[1]
            score = item[2] if len(item) > 2 else 0.0
            ys = [pt[1] for pt in box]
            xs = [pt[0] for pt in box]
            print(f"[y={min(ys):6.0f} x={min(xs):5.0f}] {text}  ({score})")
    doc.close()


if __name__ == "__main__":
    pages = [int(a) for a in sys.argv[1:]] or [6]
    main(pages)
