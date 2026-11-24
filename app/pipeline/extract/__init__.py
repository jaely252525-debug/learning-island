"""解析入口：按扩展名分派。"""
from __future__ import annotations

from pathlib import Path

from .office import extract_docx, extract_pptx
from .pdf import extract_pdf
from .textfile import extract_markdown, extract_txt
from .common import ExtractResult

DISPATCH = {
    ".pdf": lambda path, doc_id: extract_pdf(path, doc_id),
    ".docx": lambda path, doc_id: extract_docx(path),
    ".pptx": lambda path, doc_id: extract_pptx(path),
    ".md": lambda path, doc_id: extract_markdown(path),
    ".markdown": lambda path, doc_id: extract_markdown(path),
    ".txt": lambda path, doc_id: extract_txt(path),
}


def extract(path: str, doc_id: str) -> ExtractResult:
    ext = Path(path).suffix.lower()
    fn = DISPATCH.get(ext)
    if fn is None:
        raise ValueError(f"暂不支持的格式：{ext}")
    return fn(path, doc_id)
