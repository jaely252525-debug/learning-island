"""M3 端到端演示：上传真实扫描版教材 → 等后台跑 → 打印大纲章/节与页范围。"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx

BASE = "http://127.0.0.1:8010"
PDF = os.environ.get("BOOK_PDF", "你的教材.pdf")

client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(120, read=120))
token = None

with open(PDF, "rb") as f:
    r = client.post(
        "/api/documents",
        files={"file": (Path(PDF).name, f, "application/pdf")},
    )
token = r.headers.get("X-Visitor-Token")
print("upload", r.status_code, r.json())
doc_id = r.json()["id"]

h = {"X-Visitor-Token": token}
t0 = time.time()
last = None
while time.time() - t0 < 900:
    st = client.get(f"/api/documents/{doc_id}/status", headers=h).json()
    if st.get("status") != last:
        print(f"[{time.time()-t0:6.1f}s] {st.get('status')} stage={st.get('stage')} progress={st.get('progress')}")
        last = st.get("status")
    if st.get("status") in {"ready", "partial", "failed"}:
        break
    time.sleep(5)

print("最终状态：", st)
print("stats：", st.get("stats") or st.get("quality"))

outline = client.get(f"/api/documents/{doc_id}/outline", headers=h).json()
items = outline.get("nodes") or outline.get("items") or []
for ch in items:
    kids = ch.get("children") or []
    print(f"{ch.get('title')} p{ch.get('pageStart')}-{ch.get('pageEnd')} 节数={len(kids)} status={ch.get('status')}")
    for s in kids:
        print(f"    {s.get('title')} p{s.get('pageStart')}-{s.get('pageEnd')} {s.get('status')}")
print("doc_id =", doc_id)
