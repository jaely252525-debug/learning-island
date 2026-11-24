"""M4 才实现的接口占位：结构先占住，调用时明确返回 501，不假装可用。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

M4 = "该接口属于 M4（重点标注 / 评分 / 反馈）"

marks = APIRouter(prefix="/api/marks", tags=["marks"])
answers = APIRouter(prefix="/api/answers", tags=["answers"])
feedback = APIRouter(prefix="/api/feedback", tags=["feedback"])
progress = APIRouter(prefix="/api/progress", tags=["progress"])


def _todo(msg: str) -> None:
    raise HTTPException(status_code=501, detail=f"{msg}，M2 未实现")


@answers.post("/grade")
def grade_answer():
    _todo(M4)


@feedback.post("")
def post_feedback():
    _todo(M4)


@marks.get("")
def get_marks():
    _todo(M4)


@marks.put("")
def put_marks():
    _todo(M4)


@progress.get("")
def get_progress():
    _todo("进度接口")
