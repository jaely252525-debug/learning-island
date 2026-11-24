"""页码映射：印刷页 ↔ PDF 页序。

M1 只用文字层投票；M3 接上目录页 OCR 后，`offset_from_toc_pairs` 用目录里写的页码反推。
"""
from __future__ import annotations

import re
from collections import Counter


def pick_offset(votes: Counter[int], lo: int = 0, hi: int = 60, min_votes: int = 2) -> int:
    """页码偏移选举：票数最多且合理者胜，平票取更小的偏移。"""
    candidates = [(off, cnt) for off, cnt in votes.items() if lo <= off <= hi and cnt >= min_votes]
    if not candidates:
        return 0
    candidates.sort(key=lambda x: (-x[1], x[0]))
    return candidates[0][0]


def offset_from_toc_pairs(pairs: list[tuple[int, int]]) -> int:
    """pairs = [(目录页码, 该标题所在 PDF 页)]，取出现最多的差值。"""
    votes = Counter(pdf_page - printed for printed, pdf_page in pairs if printed > 0)
    if not votes:
        return 0
    best = votes.most_common(1)[0][0]
    return best if 0 <= best <= 200 else 0


def parse_toc_line(line: str) -> tuple[str, int] | None:
    """从目录行里找出“标题 + 末尾数字（页码）”。"""
    m = re.match(r"^(.*?)\s*[.·…\s]{2,}\s*(\d{1,4})\s*$", line.strip())
    if not m:
        m = re.match(r"^(.*[^\d])\s(\d{1,4})$", line.strip())
    if not m:
        return None
    title = m.group(1).strip(" .·…")
    page = int(m.group(2))
    if not title or page <= 0:
        return None
    return title, page
