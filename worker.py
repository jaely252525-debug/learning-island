"""独立 worker：python worker.py（可加 --once 跑一轮就退出）。"""
from __future__ import annotations

import sys
import time

from app.db import init_db
from app.pipeline.queue import process_once


def main() -> None:
    init_db()
    once = "--once" in sys.argv
    while True:
        did = process_once()
        if once:
            break
        if not did:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
