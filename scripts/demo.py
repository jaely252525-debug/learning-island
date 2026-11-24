"""对着真实运行的服务器跑一遍 M1 流程（演示用）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "fixtures" / "book.pdf"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=30)
    token = c.post("/api/visitors").json()["token"]
    print("1) 领到访客令牌：", token[:12] + "…")

    with open(SAMPLE, "rb") as f:
        r = c.post("/api/documents", headers={"X-Visitor-Token": token}, files={"file": (SAMPLE.name, f, "application/pdf")})
    r.raise_for_status()
    doc = r.json()
    print("2) 上传成功：", doc["id"], doc["filename"], f'{doc["status"]}/{doc["stage"]}')

    for _ in range(40):
        s = c.get(f"/api/documents/{doc['id']}/status", headers={"X-Visitor-Token": token}).json()
        if s["status"] in ("ready", "failed"):
            break
        time.sleep(0.3)
    print(
        "3) 状态：",
        s["status"],
        f'progress={s["progress"]}%',
        f'pages={s["pageCount"]}',
        f'offset={s["pageOffset"]}',
        f'textLayer={s["hasTextLayer"]}',
        f'error={s["error"]}',
    )

    o = c.get(f"/api/documents/{doc['id']}/outline", headers={"X-Visitor-Token": token}).json()
    print("4) 大纲：", o["stats"])
    for ch in o["chapters"]:
        print(f"   {ch['id']} {ch['title']}  p{ch['pageStart']}-{ch['pageEnd']}")
        for sec in ch["children"]:
            print(f"     └ {sec['id']} {sec['title']}  p{sec['pageStart']}-{sec['pageEnd']} [{sec['status']}]")
            for kn in sec["children"]:
                print(f"        · {kn['id']} {kn['title']}  p{kn['pageStart']} [{kn['status']}]")

    kids = [n for ch in o["chapters"] for sec in ch["children"] for n in sec["children"]]
    if kids:
        n = c.get(f"/api/nodes/{kids[0]['id']}", headers={"X-Visitor-Token": token}).json()
        print("5) 第一个知识点：", n["id"], n["title"])
        print("   原文要点：", n["content"]["original"][:60])
        print("   大白话：", n["content"]["plain"][0][:60])
        print("   类比：", n["content"]["analogy"][:60])
        print("   闯关：", n["game"]["template"], list(n["game"]["payload"])[:4])
        print("   题目：", len(n["questions"]), "道 /", [q["type"] for q in n["questions"]])
        print("   前置：", n["prerequisites"], "检查：", n["quality"].get("checks"))

    print("6) 报错样例：上传 .exe →", c.post("/api/documents", headers={"X-Visitor-Token": token},
                                             files={"file": ("evil.exe", b"MZ", "application/octet-stream")}).status_code)
    print("7) 删除 →", c.delete(f"/api/documents/{doc['id']}", headers={"X-Visitor-Token": token}).status_code)
    print("8) 删除后再查 →", c.get(f"/api/documents/{doc['id']}/status", headers={"X-Visitor-Token": token}).status_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
