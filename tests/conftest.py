"""测试用环境：独立临时库和存储目录，不碰 data/ 下的真实数据。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="xiaodao_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(TMP)
os.environ["AUTO_WORKER"] = "false"
os.environ["TOKEN_SECRET"] = "test-secret"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    from app.db import engine, init_db
    from app.models import Base

    init_db()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def fixtures_dir() -> Path:
    from tests.fixtures import make_fixtures

    d = TMP / "fixtures"
    d.mkdir(exist_ok=True)
    if not (d / "book.pdf").exists():
        make_fixtures.make_book_pdf(d / "book.pdf")
        make_fixtures.make_docx_no_heading(d / "notes.docx")
        make_fixtures.make_pptx_no_toc(d / "slides.pptx")
        make_fixtures.make_md(d / "note.md")
    return d


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def token(client) -> str:
    r = client.post("/api/visitors")
    assert r.status_code == 200
    return r.json()["token"]
