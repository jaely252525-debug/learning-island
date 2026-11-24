import sqlite3
from app.config import settings

print(settings.database_url)
db = settings.database_url.replace("sqlite:///", "").replace("sqlite://", "")
conn = sqlite3.connect(db)
rows = conn.execute("select document_id, level, count(*) from nodes group by document_id, level").fetchall()
for r in rows:
    print(r)
print("--- sample")
for r in conn.execute("select id, document_id, level, title from nodes where level in ('chapter','section') limit 10"):
    print(r)
