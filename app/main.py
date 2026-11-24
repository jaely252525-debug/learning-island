"""FastAPI 入口：CORS、限流、异常处理、任务轮询。"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import courses, documents, frontend, nodes, stubs
from .auth import TOKEN_HEADER, issue_token
from .config import settings
from .db import init_db
from .pipeline.queue import process_once


_hits: dict[str, deque[float]] = defaultdict(deque)
WINDOW = 60.0


def _rate_limited(key: str) -> bool:
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= settings.rate_limit_per_minute:
        return True
    q.append(now)
    return False


async def _worker_loop() -> None:
    while True:
        try:
            did = await asyncio.to_thread(process_once)
            await asyncio.sleep(0.3 if did else 1.2)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = None
    if settings.auto_worker:
        task = asyncio.create_task(_worker_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title=settings.app_name, version="0.2.0-m2", lifespan=lifespan)

origins = ["*"] if settings.allowed_origins.strip() == "*" else [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[TOKEN_HEADER],
)


@app.middleware("http")
async def limiter(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        key = request.headers.get(TOKEN_HEADER) or (request.client.host if request.client else "anon")
        if _rate_limited(key):
            return JSONResponse({"detail": "请求过于频繁，请稍后再试"}, status_code=429)
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse({"detail": "服务器内部错误"}, status_code=500)


app.include_router(documents.router)
app.include_router(courses.router)
app.include_router(frontend.router)
app.include_router(nodes.router)
app.include_router(stubs.marks)
app.include_router(stubs.answers)
app.include_router(stubs.feedback)
app.include_router(stubs.progress)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.2.0-m2", "autoWorker": settings.auto_worker}


@app.post("/api/visitors")
def new_visitor():
    """显式领一个令牌；不带令牌直接调上传接口也会自动发。"""
    return {"token": issue_token()}

