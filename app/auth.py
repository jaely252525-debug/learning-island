"""匿名访客令牌：UUID + HMAC 签名，库里只存 hash。"""
from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi import Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import Visitor, utcnow

TOKEN_HEADER = "X-Visitor-Token"


def issue_token() -> str:
    uid = uuid.uuid4().hex
    sig = hmac.new(settings.token_secret.encode(), uid.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{uid}.{sig}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_token(token: str) -> str | None:
    """校验签名，返回 uid；不合法返回 None。"""
    if not token or "." not in token:
        return None
    uid, sig = token.rsplit(".", 1)
    if len(uid) != 32 or len(sig) != 32:
        return None
    expect = hmac.new(settings.token_secret.encode(), uid.encode(), hashlib.sha256).hexdigest()[:32]
    return uid if hmac.compare_digest(expect, sig) else None


def resolve_visitor(db: Session, token: str) -> Visitor | None:
    if parse_token(token) is None:
        return None
    th = token_hash(token)
    visitor = db.scalar(select(Visitor).where(Visitor.token_hash == th))
    if visitor is None:
        visitor = Visitor(token_hash=th)
        db.add(visitor)
        db.commit()
        db.refresh(visitor)
    else:
        visitor.last_seen_at = utcnow()
        db.commit()
    return visitor


def get_visitor(
    response: Response,
    db: Session = Depends(get_session),
    x_visitor_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> Visitor:
    """带令牌就用令牌；没带或无效就发一个新令牌（回写在响应头）。"""
    token = x_visitor_token or ""
    visitor = resolve_visitor(db, token) if token else None
    if visitor is None:
        token = issue_token()
        visitor = resolve_visitor(db, token)
        response.headers[TOKEN_HEADER] = token
        response.headers["Access-Control-Expose-Headers"] = TOKEN_HEADER
    return visitor  # type: ignore[return-value]
