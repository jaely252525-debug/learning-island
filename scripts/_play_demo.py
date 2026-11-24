"""用真实教材的那份文档打印 play-data（跳过鉴权，只看字段）。"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import compat
from app.config import settings

DOC = "doc_e5165cf422d5437c9c0d"
engine = create_engine(settings.database_url)
Session = sessionmaker(bind=engine)
db = Session()

data = compat.play_data(db, DOC)
print("meta:", json.dumps(data["meta"], ensure_ascii=False))
print("CH:", json.dumps(data["CH"], ensure_ascii=False))
print("SC[1]:", json.dumps(data["SC"]["1"], ensure_ascii=False))
print("SC[3]:", json.dumps(data["SC"]["3"], ensure_ascii=False))
keys = list(data["N"])[:3]
for k in keys:
    item = data["N"][k]
    item = {**item, "o": item["o"][:40] + "…", "p": item["p"][:40] + "…", "a": item["a"][:30] + "…"}
    print(f"N[{k}]:", json.dumps(item, ensure_ascii=False))
print("AM:", data["AM"])
