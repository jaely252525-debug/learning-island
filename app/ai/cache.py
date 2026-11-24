"""AI 结果缓存：按「内容哈希 + 提示词版本 + schema 版本」存取，省钱。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AiCache
from .provider import PROMPT_VERSION, SCHEMA_VERSION


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def make_key(kind: str, hash_hex: str, impl_version: str = "v1") -> str:
    return hashlib.sha256(f"{kind}|{PROMPT_VERSION}|{SCHEMA_VERSION}|{impl_version}|{hash_hex}".encode()).hexdigest()[:40]


def get(db: Session, key: str) -> Any | None:
    row = db.get(AiCache, key)
    return row.payload if row is not None else None


def put(db: Session, key: str, kind: str, payload: Any) -> None:
    db.merge(AiCache(cache_key=key, kind=kind, payload=payload))
