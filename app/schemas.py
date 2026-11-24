"""对外数据结构（与前端原型字段对齐：camelCase 输出）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    stage: str
    progress: int
    pageCount: int = Field(serialization_alias="pageCount")
    pageOffset: int
    hasTextLayer: bool
    error: str | None = None
    quality: dict[str, Any] | None = None
    createdAt: str | None = None

    model_config = {"populate_by_name": True}


class StatusOut(BaseModel):
    id: str
    status: str
    stage: str
    progress: int
    pageCount: int
    pageOffset: int
    hasTextLayer: bool
    error: str | None = None
    quality: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] = []


class CourseOut(BaseModel):
    id: str
    title: str
    documentId: str
    status: str
    stage: str
    progress: int
    pageCount: int = 0
    sourceCount: int = 0
    error: str | None = None
    quality: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = []
    createdAt: str | None = None


class NodeOut(BaseModel):
    id: str
    parentId: str | None
    level: str
    title: str
    order: int
    pageStart: int | None = None
    pageEnd: int | None = None
    status: str
    locked: bool = False
    prerequisites: list[str] = []
    sources: list[dict[str, Any]] = []
    importance: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    children: list["NodeOut"] = []
    # —— 与前端原型对齐的别名（章：no/icon/sectionCount/page；节：no/name/page） ——
    no: int | None = None
    icon: str | None = None
    name: str | None = None
    sectionCount: int | None = None
    page: int | None = None


class NodeDetailOut(BaseModel):
    id: str
    parentId: str | None
    level: str
    title: str
    order: int
    pageStart: int | None = None
    pageEnd: int | None = None
    status: str
    locked: bool = False
    prerequisites: list[str] = []
    sources: list[dict[str, Any]] = []
    content: dict[str, Any] | None = None
    game: dict[str, Any] | None = None
    questions: list[dict[str, Any]] = []
    importance: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    # —— 与原型 N 对象对齐 ——
    num: int | None = None
    pg: str | None = None
    o: str | None = None
    p: str | None = None
    a: str | None = None
    svg: str | None = None
    g: dict[str, Any] | None = None
    pre: list[int] = []


class OutlineOut(BaseModel):
    document: DocumentOut
    chapters: list[NodeOut]
    stats: dict[str, int]


NodeOut.model_rebuild()
