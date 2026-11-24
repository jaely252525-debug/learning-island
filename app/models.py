"""数据表。字段与前端原型对齐（章→节→知识点三层用一张 nodes 表装）。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Visitor(Base):
    """匿名访客。数据按 token_hash 隔离，接口里绝不回传原令牌。"""

    __tablename__ = "visitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    quota_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    storage_key: Mapped[str] = mapped_column(String(255), default="")

    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    stage: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    page_count: Mapped[int] = mapped_column(Integer, default=0)
    page_offset: Mapped[int] = mapped_column(Integer, default=0)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Course(Base):
    """多资料合集：一个 Course 下挂多个 Document（Source），并生成一个汇总文档。"""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    document_id: Mapped[str] = mapped_column(String(40), default="", index=True)

    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    stage: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    quality_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CourseSource(Base):
    """合集里的一个原始文件，按 order_index 排序。"""

    __tablename__ = "course_sources"
    __table_args__ = (UniqueConstraint("course_id", "document_id", name="uq_course_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class DocTask(Base):
    """任务表当队列：worker 轮询；失败可重试；resume_from 支持断点续跑。"""

    __tablename__ = "doc_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    stage: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending/running/done/failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    resume_from: Mapped[str | None] = mapped_column(String(20), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    heartbeat: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)


class Page(Base):
    """页：page_no 是 PDF 页序，printed_page 是书上印的页码。"""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_no", name="uq_page"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer, index=True)
    printed_page: Mapped[int | None] = mapped_column(Integer, default=None)
    text: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    image_key: Mapped[str | None] = mapped_column(String(255), default=None)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    level: Mapped[str] = mapped_column(String(12), index=True)  # chapter / section / knowledge
    path: Mapped[str] = mapped_column(String(160), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), default="")
    page_start: Mapped[int | None] = mapped_column(Integer, default=None)
    page_end: Mapped[int | None] = mapped_column(Integer, default=None)

    status: Mapped[str] = mapped_column(String(16), default="skeleton")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)

    sources: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[dict | None] = mapped_column(JSON, default=None)
    game: Mapped[dict | None] = mapped_column(JSON, default=None)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    importance: Mapped[dict | None] = mapped_column(JSON, default=None)
    quality: Mapped[dict | None] = mapped_column(JSON, default=None)
    content_hash: Mapped[str] = mapped_column(String(64), default="")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class NodePrereq(Base):
    """前置关系单独成表，方便环检测和「被依赖次数」统计。"""

    __tablename__ = "node_prereqs"

    node_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    prereq_id: Mapped[str] = mapped_column(String(80), primary_key=True)


class Mark(Base):
    """重点标记：AI 预标注与用户覆盖分开存，用户优先。"""

    __tablename__ = "marks"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    source: Mapped[str] = mapped_column(String(8), default="ai")  # ai / user
    level: Mapped[str] = mapped_column(String(8), default="normal")  # high / normal / skip
    score: Mapped[float] = mapped_column(Float, default=0.0)
    basis: Mapped[list] = mapped_column(JSON, default=list)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str] = mapped_column(String(80), index=True)
    type: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(12), default="open")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Grade(Base):
    """简答评分留档，用于可复现与申诉。"""

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[str] = mapped_column(String(80), index=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"), index=True)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    missing: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(80), default="")
    prompt_version: Mapped[str] = mapped_column(String(24), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    stage: Mapped[str] = mapped_column(String(24), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    in_tokens: Mapped[int] = mapped_column(Integer, default=0)
    out_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_version: Mapped[str] = mapped_column(String(24), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class AiCache(Base):
    __tablename__ = "ai_cache"

    cache_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
