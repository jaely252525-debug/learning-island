"""真实模型 / mock 的合集大纲合并质量对比。

用法（先填好 .env 里的 AI_BASE_URL / AI_API_KEY / AI_MODEL）：
    python scripts/validate_merge.py --provider api --out data/merge_eval_api.json
    python scripts/validate_merge.py --provider mock --out data/merge_eval_mock.json

脚本只跑到“来源页 + 来源骨架 + 合并大纲”，不生成知识点/题目，避免真模型
验证时产生大量无关调用。会临时建一个数据库和一套 3 份 PPT 的测试资料。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在 import app.* 之前设置，settings 是模块级单例。
parser = argparse.ArgumentParser()
parser.add_argument("--provider", choices=["api", "mock"], default="api")
parser.add_argument("--out", default="")
args = parser.parse_args()

tmp = Path(tempfile.mkdtemp(prefix="merge_eval_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'eval.db').as_posix()}"
os.environ["DATA_DIR"] = str(tmp)
os.environ["AUTO_WORKER"] = "false"
os.environ["TOKEN_SECRET"] = "merge-eval-secret"
os.environ["AI_PROVIDER"] = args.provider

from sqlalchemy import select  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Pt  # noqa: E402

from app.ai.provider import get_provider, validate  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Course, CourseSource, Document  # noqa: E402
from app.pipeline.course import (  # noqa: E402
    _make_source_outline,
    _nodes_of,
    _plans_from_merged,
    _store_course_pages,
)
from app.pipeline.runner import process_document  # noqa: E402

DECK = [
    (
        "01_总论与资源.pptx",
        [
            ("绪论", "药用植物过程工程研究药用植物的采收、加工与资源利用。"),
            ("药用植物资源概述", "药用植物资源包括野生与栽培资源，按药用部位分类。"),
            ("资源分布与生境", "资源分布受气候、土壤和海拔影响，道地药材有明确产区。"),
            ("采收与产地加工", "采收期影响有效成分含量，产地加工包括干燥、分级和贮藏。"),
            ("课堂练习一", "比较不同采收期对有效成分含量的影响。"),
        ],
    ),
    (
        "02_提取技术.pptx",
        [
            ("提取技术总论", "提取是把有效成分从药材组织转移到溶剂中的过程。"),
            ("药用植物资源", "资源品质决定提取原料的批次稳定性。"),
            ("资源分布", "不同产区的原料在成分含量上存在差异。"),
            ("传统溶剂提取", "传统溶剂提取包括煎煮、浸渍、渗滤和回流。"),
            ("超临界CO2萃取", "超临界 CO2 萃取适合热敏性成分，接近室温操作。"),
            ("超声辅助提取", "超声空化作用破坏细胞壁，缩短提取时间。"),
        ],
    ),
    (
        "03_分离与纯化.pptx",
        [
            ("提取技术绪论", "提取之后通常需要分离和纯化，才能得到目标成分。"),
            ("微波辅助萃取", "微波从物料内部加热，速度快但要注意温度均匀。"),
            ("分离纯化概述", "分离纯化按分子大小、极性、溶解度等性质设计。"),
            ("色谱分离", "色谱分离利用组分在固定相和流动相之间的分配差异。"),
            ("膜分离", "膜分离按孔径和截留分子量分级，适合热敏物料。"),
        ],
    ),
]


def make_decks(root: Path) -> list[Path]:
    out = []
    for name, slides in DECK:
        prs = Presentation()
        layout = prs.slide_layouts[1]
        for title, body in slides:
            slide = prs.slides.add_slide(layout)
            slide.shapes.title.text = title
            tf = slide.placeholders[1].text_frame
            tf.text = f"{title}：{body}"
            tf.paragraphs[0].font.size = Pt(16)
        path = root / name
        prs.save(str(path))
        out.append(path)
    return out


def sim(a: str, b: str) -> float:
    a = "".join(str(a or "").lower().split())
    b = "".join(str(b or "").lower().split())
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def main() -> None:
    if args.provider == "api" and not (settings.ai_api_key and settings.ai_base_url):
        raise SystemExit("AI_PROVIDER=api 但没有配置 AI_API_KEY / AI_BASE_URL，请先填 .env")

    deck_dir = tmp / "decks"
    deck_dir.mkdir(parents=True)
    paths = make_decks(deck_dir)
    mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    with TestClient(app) as client:
        token = client.post("/api/visitors").json()["token"]
        handles = [(p.name, open(p, "rb"), mime) for p in paths]
        try:
            r = client.post(
                "/api/courses",
                headers={"X-Visitor-Token": token},
                files=[("files", h) for h in handles],
                data={"title": "药用植物过程工程 · 三讲合集"},
            )
        finally:
            for _, h, _ in handles:
                h.close()
        if r.status_code != 201:
            raise SystemExit(f"创建合集失败：{r.status_code} {r.text[:300]}")
        course_id = r.json()["id"]

    db = SessionLocal()
    try:
        course = db.get(Course, course_id)
        rows = db.scalars(
            select(CourseSource)
            .where(CourseSource.course_id == course_id)
            .order_by(CourseSource.order_index)
        ).all()
        sources = [db.get(Document, row.document_id) for row in rows]
        sources = [s for s in sources if s is not None]
        for src in sources:
            process_document(db, src.id, stop_after="outline")

        payload = [_make_source_outline(course, src, _nodes_of(db, src)) for src in sources]
        provider = get_provider()
        merged = None
        error = ""
        try:
            merged = provider.merge_outline(payload)
        except Exception as exc:  # noqa: BLE001 - 验证脚本需要把错误原样报出来
            error = f"{type(exc).__name__}: {exc}"
        if error:
            print(json.dumps({"provider": provider.name, "error": error}, ensure_ascii=False, indent=2))
            raise SystemExit(1)

        schema_errors = validate("course_outline", merged)
        aggregate = db.get(Document, course_id)
        ranges = _store_course_pages(
            db,
            course,
            aggregate,
            [(row, db.get(Document, row.document_id)) for row in rows],
        )
        plans = _plans_from_merged(merged, ranges) if not schema_errors else []

        sections = []
        for ch in (merged.get("chapters") or []):
            for sec in (ch.get("sections") or []):
                sections.append({"chapter": ch.get("title", ""), "title": sec.get("title", ""),
                                 "refs": sec.get("refs") or []})
        duplicate_pairs = []
        for i in range(len(sections)):
            for j in range(i + 1, len(sections)):
                score = sim(sections[i]["title"], sections[j]["title"])
                if score >= 0.72:
                    duplicate_pairs.append({
                        "a": sections[i]["title"], "b": sections[j]["title"],
                        "score": round(score, 3),
                    })
        valid_source_ids = {s.id for s in sources}
        bad_refs = [
            {"section": sec["title"], "ref": ref}
            for sec in sections
            for ref in sec["refs"]
            if str(ref.get("sourceId") or "") not in valid_source_ids
            or int(ref.get("pageStart") or 0) < 1
            or int(ref.get("pageEnd") or 0) < int(ref.get("pageStart") or 0)
        ]
        source_covered = sorted(
            {ref.get("sourceId") for sec in sections for ref in sec["refs"] if ref.get("sourceId")}
        )

        report = {
            "provider": getattr(provider, "name", "?"),
            "model": settings.ai_model if args.provider == "api" else "mock",
            "courseTitle": merged.get("title"),
            "schemaErrors": schema_errors,
            "sourceFiles": [s.filename for s in sources],
            "sourceCount": len(sources),
            "returnedChapters": len(merged.get("chapters") or []),
            "returnedSections": len(sections),
            "plansBuilt": len(plans),
            "duplicateTitlePairs": duplicate_pairs,
            "badRefs": bad_refs,
            "sourcesCovered": source_covered,
            "sourcesMissing": sorted(valid_source_ids - set(source_covered)),
            "outline": [
                {
                    "chapter": ch.get("title"),
                    "sections": [
                        {"title": sec.get("title"), "refs": len(sec.get("refs") or [])}
                        for sec in (ch.get("sections") or [])
                    ],
                }
                for ch in (merged.get("chapters") or [])
            ],
            "sourceInputs": [
                {
                    "file": p["title"], "chapters": len(p["chapters"]),
                    "sections": sum(len(c["sections"]) for c in p["chapters"]),
                }
                for p in payload
            ],
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"\n写入 {out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
