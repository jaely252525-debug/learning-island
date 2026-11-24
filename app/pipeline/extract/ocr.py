"""OCR 引擎封装。

默认 RapidOCR（PP-OCR 模型的 ONNX 版，本地跑、无需密钥）。
换 PaddleOCR / 云 OCR 只需要实现同名接口：`ocr_image()` 返回 `[{text, x, y, conf}]`。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf

from ...config import settings
from ...storage.files import page_image_key, page_image_path


@dataclass
class OcrLine:
    text: str
    x: float
    y: float
    conf: float
    h: float = 0.0


class OcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # 延迟导入，没装也不影响 M1/M2

        self._engine = RapidOCR()
        self.calls = 0

    def ocr_image(self, image: np.ndarray) -> list[OcrLine]:
        self.calls += 1
        result, _ = self._engine(image)
        lines: list[OcrLine] = []
        for item in result or []:
            box, text = item[0], str(item[1])
            conf = float(item[2]) if len(item) > 2 else 0.0
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            lines.append(
                OcrLine(
                    text=text.strip(),
                    x=float(min(xs)),
                    y=float(min(ys)),
                    conf=conf,
                    h=float(max(ys) - min(ys)),
                )
            )
        return lines

    def page_size(self, pdf_path: str, page_no: int, doc_id: str, dpi: int | None = None) -> tuple[int, int]:
        dpi = dpi or settings.ocr_dpi
        path = page_image_path(doc_id, page_no, dpi)
        if not path.exists():
            with pymupdf.open(pdf_path) as pdf:
                pix = pdf.load_page(page_no - 1).get_pixmap(dpi=dpi)
                pix.save(str(path))
        pix = pymupdf.Pixmap(str(path))
        return pix.width, pix.height

    def ocr_page(self, pdf_path: str, page_no: int, doc_id: str, dpi: int | None = None) -> list[OcrLine]:
        """渲染并识别一页；页面图落盘缓存，供前端和复查用。"""
        dpi = dpi or settings.ocr_dpi
        path = page_image_path(doc_id, page_no, dpi)
        if not path.exists():
            with pymupdf.open(pdf_path) as pdf:
                pix = pdf.load_page(page_no - 1).get_pixmap(dpi=dpi)
                pix.save(str(path))
        pix = pymupdf.Pixmap(str(path))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        return self.ocr_image(img)


_engine: OcrEngine | None = None


def get_engine() -> OcrEngine:
    global _engine
    if _engine is None:
        _engine = OcrEngine()
    return _engine


def page_image_relative(doc_id: str, page_no: int, dpi: int | None = None) -> str:
    return page_image_key(doc_id, page_no, dpi)
