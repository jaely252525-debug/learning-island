"""诊断：把 partial 节点的问题打出来。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8010"
ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)
    token = c.post("/api/visitors").json()["token"]
    with open(ROOT / "tests" / "fixtures" / "book.pdf", "rb") as f:
        doc = c.post("/api/documents", headers={"X-Visitor-Token": token}, files={"file": ("book.pdf", f, "application/pdf")}).json()
    for _ in range(40):
        s = c.get(f"/api/documents/{doc['id']}/status", headers={"X-Visitor-Token": token}).json()
        if s["status"] in ("ready", "partial", "failed"):
            break
        time.sleep(0.3)
    o = c.get(f"/api/documents/{doc['id']}/outline", headers={"X-Visitor-Token": token}).json()
    for ch in o["chapters"]:
        for sec in ch["children"]:
            for kn in sec["children"]:
                if kn["status"] != "ready":
                    n = c.get(f"/api/nodes/{kn['id']}", headers={"X-Visitor-Token": token}).json()
                    print(kn["id"], kn["title"], "→", json.dumps(n["quality"], ensure_ascii=False, indent=1))
                    print("   sources:", n["sources"])
                    print("   qs:", [(q["id"], q["sourceRef"]) for q in n["questions"]])
    c.delete(f"/api/documents/{doc['id']}", headers={"X-Visitor-Token": token})


if __name__ == "__main__":
    main()
