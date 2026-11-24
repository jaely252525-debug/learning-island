"""接口端到端：上传 → 任务 → 状态 → 大纲 → 删除。"""
from __future__ import annotations

from pathlib import Path

from app.pipeline.queue import process_once


def _upload(client, token: str, path: Path, mime: str = "application/pdf"):
    with open(path, "rb") as f:
        return client.post(
            "/api/documents",
            headers={"X-Visitor-Token": token},
            files={"file": (path.name, f, mime)},
        )


def _drain(max_rounds: int = 5) -> None:
    for _ in range(max_rounds):
        if not process_once():
            break


def test_upload_pdf_full_flow(client, token, fixtures_dir: Path):
    r = _upload(client, token, fixtures_dir / "book.pdf")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["id"].startswith("doc_") and doc["status"] in ("uploaded", "extracting", "outlining")

    _drain()

    s = client.get(f"/api/documents/{doc['id']}/status", headers={"X-Visitor-Token": token}).json()
    assert s["status"] in ("ready", "partial"), s
    assert s["pageCount"] == 12
    assert s["pageOffset"] == 2
    assert s["tasks"][0]["status"] == "done"

    o = client.get(f"/api/documents/{doc['id']}/outline", headers={"X-Visitor-Token": token}).json()
    assert o["stats"]["chapters"] == 2
    assert [c["title"] for c in o["chapters"]] == ["第一章 总论", "第二章 工艺"]
    assert len(o["chapters"][0]["children"]) == 2
    assert o["chapters"][1]["children"][0]["title"] == "2.1 超声辅助提取"
    # 页范围按印刷页暴露（偏移 2 → 原本 PDF 第 3 页变成印刷页 1）
    assert o["chapters"][0]["pageStart"] == 1
    assert o["document"]["pageOffset"] == 2
    assert o["stats"]["knowledge"] >= 4


def test_upload_without_token_issues_one(client, fixtures_dir: Path):
    r = _upload(client, "", fixtures_dir / "note.md", "text/markdown")
    assert r.status_code == 201
    assert r.headers.get("X-Visitor-Token")
    _drain()
    token = r.headers["X-Visitor-Token"]
    o = client.get(f"/api/documents/{r.json()['id']}/outline", headers={"X-Visitor-Token": token}).json()
    assert o["stats"]["chapters"] == 1


def test_reject_bad_extension(client, token, fixtures_dir: Path, tmp_path: Path):
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"MZ")
    r = _upload(client, token, bad, "application/octet-stream")
    assert r.status_code == 415


def test_quantities_for_office_files(client, token, fixtures_dir: Path):
    r = _upload(client, token, fixtures_dir / "slides.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    assert r.status_code == 201
    _drain()
    o = client.get(f"/api/documents/{r.json()['id']}/outline", headers={"X-Visitor-Token": token}).json()
    assert o["stats"]["chapters"] == 1
    assert o["stats"]["sections"] == 6


def test_delete_removes_rows_and_files(client, token, fixtures_dir: Path):
    from app.config import settings

    r = _upload(client, token, fixtures_dir / "note.md", "text/markdown")
    doc_id = r.json()["id"]
    _drain()
    d = client.delete(f"/api/documents/{doc_id}", headers={"X-Visitor-Token": token})
    assert d.status_code == 204
    assert not (settings.data_dir / "uploads" / doc_id).exists()
    s = client.get(f"/api/documents/{doc_id}/status", headers={"X-Visitor-Token": token})
    assert s.status_code == 404


def test_other_visitor_cannot_read(client, token, fixtures_dir: Path):
    r = _upload(client, token, fixtures_dir / "book.pdf")
    doc_id = r.json()["id"]
    other = client.post("/api/visitors").json()["token"]
    s = client.get(f"/api/documents/{doc_id}/status", headers={"X-Visitor-Token": other})
    assert s.status_code == 404


def test_rate_limit_blocks_burst(client, token):
    from app.config import settings

    ok = 429
    hit = None
    for _ in range(settings.rate_limit_per_minute + 5):
        resp = client.get("/api/health", headers={"X-Visitor-Token": token})
        if resp.status_code == 429:
            hit = resp
            break
    assert hit is not None and hit.status_code == 429
