import sqlite3
from app.config import settings

db = settings.database_url.replace("sqlite:///", "")
conn = sqlite3.connect(db)
doc = "doc_e5165cf422d5437c9c0d"
print(conn.execute("select level, status, count(*) from nodes where document_id=? group by level, status", (doc,)).fetchall())
print("pages ocr'd:", conn.execute("select count(*) from pages where document_id=? and length(text)>0", (doc,)).fetchone())
print("first knowledge:", conn.execute("select id, title, page_start, status from nodes where document_id=? and level='knowledge' order by id limit 3", (doc,)).fetchall())
print("sections empty:", conn.execute("select count(*) from nodes where document_id=? and level='section' and status!='structured'", (doc,)).fetchone())
