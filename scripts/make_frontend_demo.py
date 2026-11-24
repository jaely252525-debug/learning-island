"""把原型 HTML 改成吃后端 /play-data 的版本，并把真实教材那份文档挪到演示令牌名下。

输出：项目根目录 `药用植物岛 · 教材试玩（接后端）.html`
"""
import os
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8010"
SRC = Path(os.environ.get("PROTOTYPE_HTML", "你的原型.html"))
OUT = Path(__file__).resolve().parents[1] / "药用植物岛 · 教材试玩（接后端）.html"
DOC = "doc_e5165cf422d5437c9c0d"

# 1) 领一个演示令牌，并把它绑到真实教材那份文档上（库里只存 hash，原令牌找不回来）
c = httpx.Client(base_url=BASE, timeout=30)
token = c.post("/api/visitors").json()["token"]
c.get(f"/api/documents/{DOC}/outline", headers={"X-Visitor-Token": token})  # 触发 visitor 落库

db_path = Path(__file__).resolve().parents[1] / "data" / "xiaodao.db"
conn = sqlite3.connect(db_path)
th = hashlib.sha256(token.encode()).hexdigest()
row = conn.execute("select id from visitors where token_hash=?", (th,)).fetchone()
assert row, "visitor 没建出来"
vid = row[0]
conn.execute("update documents set visitor_id=? where id=?", (vid, DOC))
conn.commit()
n = conn.execute("select count(*) from documents where id=? and visitor_id=?", (DOC, vid)).fetchone()[0]
print("绑定文档：", DOC, "→ visitor", vid, "rows", n)

d = c.get(f"/api/documents/{DOC}/play-data", headers={"X-Visitor-Token": token}).json()
print("拿到的数据：", d["meta"])

# 2) 改写原型
html = SRC.read_text(encoding="utf-8")

html, n1 = re.subn(r"const CH=\[.*?\];", "let CH=[];", html, count=1)
html, n2 = re.subn(r"const SC=\{.*?\};", "let SC={};", html, count=1)
html, n3 = re.subn(r"const N=\{.*?\nconst SK=", "let N={};\nconst SK=", html, count=1, flags=re.S)
html, n4 = re.subn(r"const AM=\{.*?\};", "let AM={};", html, count=1)
html, n5 = re.subn(r"const CM=\{.*?\};", "let CM={};", html, count=1)
assert all(x == 1 for x in (n1, n2, n3, n4, n5)), (n1, n2, n3, n4, n5)

boot = """
<style>#net{position:fixed;left:0;right:0;bottom:0;background:#fff5e6;color:#7a4a00;font:13px/1.6 system-ui;padding:8px 12px;z-index:9;display:none}</style>
<div id="net"></div>
<script>
const API_BASE="http://127.0.0.1:8010";
const DOC_ID="%s";
const TOKEN="%s";
(async function boot(){
  const net=document.getElementById('net');
  try{
    const r=await fetch(`${API_BASE}/api/documents/${DOC_ID}/play-data`,{headers:{'X-Visitor-Token':TOKEN}});
    if(!r.ok) throw new Error('HTTP '+r.status+' '+(await r.text()).slice(0,120));
    const d=await r.json();
    CH=d.CH; SC=d.SC; N=d.N; AM=d.AM; CM=d.CM;
    // 原型一张图只画 5 个据点；真实数据点多，按全书顺序重排坐标，避免叠在一起
    const keys=Object.keys(N);
    keys.forEach((k,i)=>N[k].pos=[i%%2?72:28, 8+84*i/Math.max(1,keys.length-1)]);
    S.doc=1; S.up=d.meta.filename||'真实教材';
    map(); view('arch');
    net.style.display='block';
    net.textContent='已接后端：'+d.meta.filename+' · 共 '+d.meta.chapters+' 章 / '+d.meta.sections+' 节 / '+d.meta.knowledge+' 个知识点（待生成 '+d.meta.pending+'）';
  }catch(e){
    net.style.display='block';
    net.textContent='后端没连上：'+e.message+'（确认 uvicorn 在 8010 跑着）';
  }
})();
</script>
""" % (DOC, token)

html = html.replace("map();view(S.doc?'arch':'home');", boot.strip(), 1)
OUT.write_text(html, encoding="utf-8")
print("写出：", OUT, OUT.stat().st_size, "bytes")
