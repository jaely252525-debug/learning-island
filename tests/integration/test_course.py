"""合集接口端到端：两份 PPT 合并成一份大纲，再补一份资料。"""
from __future__ import annotations

from pathlib import Path

from app.pipeline.queue import process_once

PPT_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _drain(max_rounds: int = 6) -> None:
    for _ in range(max_rounds):
        if not process_once():
            break


def _create_course(client, token: str, fixtures_dir: Path, title: str = "两套提取工艺"):
    files = []
    for name in ("A.pptx", "B.pptx"):
        path = fixtures_dir / "slides.pptx"
        files.append(("files", (name, open(path, "rb"), PPT_MIME)))
    try:
        return client.post(
            "/api/courses",
            headers={"X-Visitor-Token": token},
            files=files,
            data={"title": title},
        )
    finally:
        for _, (_, handle, _) in files:
            handle.close()


def test_course_merges_two_ppts_into_one_outline(client, token, fixtures_dir: Path):
    r = _create_course(client, token, fixtures_dir)
    assert r.status_code == 201, r.text
    course = r.json()
    assert course["sourceCount"] == 2
    assert course["title"] == "两套提取工艺"

    _drain()
    s = client.get(f"/api/courses/{course['id']}/status", headers={"X-Visitor-Token": token}).json()
    assert s["status"] in ("ready", "partial"), s
    assert s["pageCount"] == 12
    assert s["sourceCount"] == 2

    o = client.get(f"/api/courses/{course['id']}/outline", headers={"X-Visitor-Token": token}).json()
    assert o["stats"]["chapters"] == 1
    assert o["stats"]["sections"] == 6
    assert o["stats"]["knowledge"] >= 4
    first_section = o["chapters"][0]["children"][0]
    assert len(first_section["sources"]) == 2
    assert {item["sourceName"] for item in first_section["sources"]} == {"A.pptx", "B.pptx"}

    p = client.get(f"/api/courses/{course['id']}/play-data", headers={"X-Visitor-Token": token})
    assert p.status_code == 200
    data = p.json()
    assert data["meta"]["courseId"] == course["id"]
    assert len(data["meta"]["sources"]) == 2
    assert data["CH"][0][2] == "综合资料" or data["CH"][0][2] == "两套提取工艺"
    assert len(data["N"]) >= 4


def test_course_accepts_more_sources_and_rebuilds(client, token, fixtures_dir: Path):
    r = _create_course(client, token, fixtures_dir)
    assert r.status_code == 201
    course_id = r.json()["id"]
    _drain()

    with open(fixtures_dir / "slides.pptx", "rb") as f:
        add = client.post(
            f"/api/courses/{course_id}/sources",
            headers={"X-Visitor-Token": token},
            files=[("files", ("C.pptx", f, PPT_MIME))],
        )
    assert add.status_code == 201, add.text
    assert add.json()["sourceCount"] == 3
    _drain()

    s = client.get(f"/api/courses/{course_id}/status", headers={"X-Visitor-Token": token}).json()
    assert s["status"] in ("ready", "partial"), s
    assert s["pageCount"] == 18
    o = client.get(f"/api/courses/{course_id}/outline", headers={"X-Visitor-Token": token}).json()
    assert o["stats"]["sections"] == 6
    assert len(o["chapters"][0]["children"][0]["sources"]) == 3
