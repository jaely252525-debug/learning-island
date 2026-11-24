"""文件落盘。路径里不放用户文件名，避免路径注入和隐私泄漏。"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import settings


def doc_dir(doc_id: str) -> Path:
    d = settings.data_dir / "uploads" / doc_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_source(doc_id: str, ext: str, data: bytes) -> str:
    path = doc_dir(doc_id) / f"source{ext}"
    path.write_bytes(data)
    return str(path.relative_to(settings.data_dir)).replace("\\", "/")


def source_path(storage_key: str) -> Path:
    return settings.data_dir / storage_key


def page_image_path(doc_id: str, page_no: int, dpi: int | None = None) -> Path:
    d = settings.data_dir / "pages" / doc_id
    d.mkdir(parents=True, exist_ok=True)
    name = f"p{page_no:04d}.png" if dpi is None else f"p{page_no:04d}_{dpi}.png"
    return d / name


def page_image_key(doc_id: str, page_no: int, dpi: int | None = None) -> str:
    name = f"p{page_no:04d}.png" if dpi is None else f"p{page_no:04d}_{dpi}.png"
    return f"pages/{doc_id}/{name}"


def delete_document_files(doc_id: str) -> None:
    shutil.rmtree(settings.data_dir / "uploads" / doc_id, ignore_errors=True)
    shutil.rmtree(settings.data_dir / "pages" / doc_id, ignore_errors=True)
