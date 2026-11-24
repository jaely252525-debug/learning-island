"""M3 探针：对真实教材 PDF 跑目录 OCR，和原型里的 CH/SC 对照。"""
from __future__ import annotations

import os
import time

from app.config import settings
from app.pipeline.extract.pdf import extract_pdf

PDF = os.environ.get("BOOK_PDF", "你的教材.pdf")

# 原型 HTML 里写死的期望值（只做验收对照，不参与解析）
CH = [(1, "绪论", 3, 1), (2, "药用植物资源", 2, 11), (3, "过程工程原理与生态产业集成", 6, 50),
      (4, "含油脂果实或种子药用植物", 5, 83), (5, "富含淀粉药用植物", 6, 110),
      (6, "富含纤维药用植物", 6, 151), (7, "富分泌组织药用植物", 5, 182),
      (8, "挥发油药用植物资源", 5, 202), (9, "有毒药用植物", 6, 238),
      (10, "富色素药用植物资源", 5, 267)]


def main() -> None:
    settings.ensure_dirs()
    t0 = time.time()
    res = extract_pdf(PDF, "doc_probe")
    print(f"用时 {time.time() - t0:.1f}s  method={res.method} offset={res.page_offset} pages={res.page_count}")
    print("stats:", res.stats)
    print("warnings:", res.warnings)

    chapters = [t for t in res.teeth if t.level == 1]
    sections = [t for t in res.teeth if t.level == 2]
    print(f"识别到 {len(chapters)} 章 / {len(sections)} 节")
    sec_by_ch: dict[int, list] = {}
    for s in sections:
        cno = int(str(s.title).split(".")[0])
        sec_by_ch.setdefault(cno, []).append(s)

    ok_titles = 0
    ok_pages = 0
    for cno, title, sec_count, page in CH:
        got = next((c for c in chapters if c.title.startswith(f"第{cno}章") or c.title.startswith(str(cno))), None)
        got_title = got.title if got else "—"
        got_secs = len(sec_by_ch.get(cno, []))
        # 书签页码在 PDF 页序，tes 减 offset 才是印刷页
        got_page = (got.page - res.page_offset) if got else None
        hit_t = title[:6] in got_title
        hit_p = got_page == page
        ok_titles += hit_t
        ok_pages += hit_p
        print(f"第{cno}章 期望({title[:12]}, {sec_count} 节, p{page}) | 得到({got_title[:20]}, {got_secs} 节, p{got_page}) {'✓' if hit_t and hit_p else '✗'}")

    print(f"标题命中 {ok_titles}/10，起始页命中 {ok_pages}/10，节数分布 {[len(sec_by_ch.get(c[0], [])) for c in CH]}")
    print("前 8 个节：", [(s.title, s.page - res.page_offset) for s in sections[:8]])


if __name__ == "__main__":
    main()
