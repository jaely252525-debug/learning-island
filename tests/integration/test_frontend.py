"""前端字段对齐：play-data 的 CH/SC/N 结构与原型常量一致。"""
from __future__ import annotations

from pathlib import Path

from app.pipeline.queue import process_once


def _upload(client, token: str, path: Path) -> str:
    with open(path, "rb") as f:
        r = client.post(
            "/api/documents",
            headers={"X-Visitor-Token": token},
            files={"file": (path.name, f, "application/pdf")},
        )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _run(max_rounds: int = 6) -> None:
    for _ in range(max_rounds):
        if not process_once():
            break


def test_outline_has_prototype_aliases(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    outline = client.get(f"/api/documents/{doc_id}/outline", headers={"X-Visitor-Token": token}).json()
    ch = outline["chapters"][0]
    assert ch["no"] == 1
    assert ch["icon"] and ch["name"]
    assert ch["sectionCount"] == len(ch["children"])
    assert ch["page"] == ch["pageStart"]
    sec = ch["children"][0]
    assert sec["no"] == 1
    assert sec["name"] and not sec["name"][:1].isdigit()
    assert sec["page"] == sec["pageStart"]


def test_play_data_shape(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    data = client.get(f"/api/documents/{doc_id}/play-data", headers={"X-Visitor-Token": token}).json()
    assert set(data) >= {"CH", "SC", "N", "AM", "CM", "meta"}

    for row in data["CH"]:
        assert len(row) == 5
        assert isinstance(row[0], int) and row[0] >= 1
        assert isinstance(row[2], str) and isinstance(row[3], int)

    ch_no = data["CH"][0][0]
    sections = data["SC"][str(ch_no)]
    assert len(sections) == data["CH"][0][3]
    for s in sections:
        assert len(s) == 2 and isinstance(s[0], str) and isinstance(s[1], int)

    assert data["N"], "应至少有一个知识点"
    for key, item in data["N"].items():
        assert key.isdigit()
        assert {"e", "t", "pos", "pre", "pg", "o", "p", "a", "svg", "g", "id", "sid"} <= set(item)
        assert len(item["pos"]) == 2
        assert isinstance(item["pre"], list)
        # sid 用章.节编号，前端靠它把据点分到对应的小岛
        cno, sno = item["sid"].split(".")
        assert cno.isdigit() and sno.isdigit()
        if item["g"]:
            assert item["g"]["type"] in {"match", "order", "choice"}

    # 详情接口的兼容字段与 play-data 对得上
    first_id = data["N"]["1"]["id"]
    node = client.get(f"/api/nodes/{first_id}", headers={"X-Visitor-Token": token}).json()
    assert node["num"] == 1
    assert node["pg"]
    assert node["o"] and node["p"] and node["a"]
    assert node["g"] == data["N"]["1"]["g"]
