"""HTTP 验证 /play-data：上传小样本 → 等自动 worker → 拉字段。"""
import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8010"
PDF = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "book.pdf"

c = httpx.Client(base_url=BASE, timeout=60)
with open(PDF, "rb") as f:
    r = c.post("/api/documents", files={"file": (PDF.name, f, "application/pdf")})
token = r.headers.get("X-Visitor-Token")
doc_id = r.json()["id"]
h = {"X-Visitor-Token": token}
print("upload", r.status_code, doc_id)

for _ in range(60):
    st = c.get(f"/api/documents/{doc_id}/status", headers=h).json()
    if st["status"] in ("ready", "partial", "failed"):
        break
    time.sleep(2)
print("status", st["status"], st.get("error"))

d = c.get(f"/api/documents/{doc_id}/play-data", headers=h).json()
print("meta", json.dumps(d["meta"], ensure_ascii=False))
print("CH", json.dumps(d["CH"], ensure_ascii=False))
print("SC", json.dumps(d["SC"], ensure_ascii=False))
for k in list(d["N"])[:2]:
    item = d["N"][k]
    print(f"N[{k}] keys={sorted(item)} type={item['g'] and item['g']['type']} pre={item['pre']} pg={item['pg']}")

node = c.get(f"/api/nodes/{d['N'][list(d['N'])[0]]['id']}", headers=h).json()
print("detail num/pg/g:", node["num"], node["pg"], node["g"]["type"], "pre", node["pre"])
