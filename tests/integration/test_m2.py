"""M2：知识点、讲解、闯关、题目、出处校验、缓存、重新生成。"""
from __future__ import annotations

from pathlib import Path

from app.ai import get_provider, reset_provider, validate
from app.pipeline.queue import process_once


def _upload(client, token: str, path: Path):
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


def _outline(client, token: str, doc_id: str):
    return client.get(f"/api/documents/{doc_id}/outline", headers={"X-Visitor-Token": token}).json()


def _knowledge_ids(outline: dict) -> list[str]:
    return [n["id"] for ch in outline["chapters"] for sec in ch["children"] for n in sec["children"]]


def test_generation_produces_full_nodes(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    outline = _outline(client, token, doc_id)
    ids = _knowledge_ids(outline)
    assert len(ids) >= 4, outline["stats"]

    node = client.get(f"/api/nodes/{ids[0]}", headers={"X-Visitor-Token": token}).json()
    assert node["level"] == "knowledge"
    assert node["content"]["original"]
    assert len(node["content"]["plain"]) == 3
    assert node["content"]["analogy"]
    assert node["game"]["template"] in ("match", "order", "scenario")
    assert len(node["questions"]) >= 3
    for q in node["questions"]:
        assert q["sourceRef"]["page"] >= 1
        assert q["id"].startswith("q_")


def test_questions_are_schema_valid(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    outline = _outline(client, token, doc_id)
    for nid in _knowledge_ids(outline):
        node = client.get(f"/api/nodes/{nid}", headers={"X-Visitor-Token": token}).json()
        assert validate("questions", node["questions"]) == [], nid
        assert validate("game", node["game"]) == [], nid
        # 存储时 sources 挂在节点上（与文档第 6 节结构一致），校验时拼回去
        assert validate("node_content", {**node["content"], "sources": node["sources"]}) == [], nid
        assert len(node["questions"]) >= 3


def test_cache_avoids_second_calls(client, token, fixtures_dir: Path):
    reset_provider()
    provider = get_provider()
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    first = dict(provider.calls)

    # 同内容重新跑一遍（缓存命中）：把文档状态拉回 generating 再执行
    from app.db import SessionLocal
    from app.models import Document

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        doc.status = "generating"
        db.commit()
    _run()
    second = dict(provider.calls)
    assert second.get("explain", 0) == first.get("explain", 0), (first, second)


def test_regenerate_returns_content(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    ids = _knowledge_ids(_outline(client, token, doc_id))
    r = client.post(f"/api/nodes/{ids[0]}/regenerate", headers={"X-Visitor-Token": token})
    assert r.status_code == 200, r.text
    assert r.json()["content"]["original"]


def test_prerequisites_chain(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    ids = _knowledge_ids(_outline(client, token, doc_id))
    node = client.get(f"/api/nodes/{ids[1]}", headers={"X-Visitor-Token": token}).json()
    assert node["prerequisites"], node
    assert len(node["prerequisites"]) >= 1


def test_patch_is_not_implemented(client, token, fixtures_dir: Path):
    doc_id = _upload(client, token, fixtures_dir / "book.pdf")
    _run()
    ids = _knowledge_ids(_outline(client, token, doc_id))
    r = client.patch(f"/api/nodes/{ids[0]}", json={"title": "改个名"}, headers={"X-Visitor-Token": token})
    assert r.status_code == 501
