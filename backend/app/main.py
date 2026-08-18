"""FastAPI 应用入口 — 见 docs/03-api.md。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import queue
from app.models import ChatConfig
from app.renderer import render_template
from app.storage import ALLOWED_MIME, MAX_UPLOAD_SIZE, OUTPUTS, UPLOADS

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("main")

app = FastAPI(title="WeChat Video Generator", lifespan=queue.lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS)), name="outputs")


# ---------- 基础 ----------

@app.get("/health")
def health():
    return {"status": "ok", "workers": queue.WORKER_COUNT, "queue_size": queue.queue_size()}


# ---------- 上传 ----------

@app.post("/api/upload")
async def upload(file: UploadFile = File(...), kind: str = Form("image")):
    if kind not in ("avatar", "image"):
        raise HTTPException(400, "kind must be 'avatar' or 'image'")
    ext = ALLOWED_MIME.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(400, f"unsupported file type: {file.content_type}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            413, f"file exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)}MB limit"
        )
    name = f"{uuid.uuid4().hex}.{ext}"
    (UPLOADS / name).write_bytes(data)
    logger.info("Uploaded %s (kind=%s, %d bytes)", name, kind, len(data))
    return {"url": f"/uploads/{name}", "kind": kind}


# ---------- 预览 / 渲染 ----------

@app.post("/api/preview-html")
def preview_html(config: ChatConfig):
    """接收 ChatConfig,返回拼好的 HTML(只拼模板,不录制)。"""
    return {"html": render_template(config)}


@app.post("/api/render", status_code=202)
def render(config: ChatConfig):
    """接收 ChatConfig,入队,返回 job_id。"""
    try:
        job_id = queue.enqueue(config)
    except queue.QueueFullError:
        raise HTTPException(503, "queue is full, please try again later")
    logger.info("Render requested, job=%s", job_id)
    return {"job_id": job_id}


# ---------- 任务状态 / SSE ----------

@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    status = queue.get_job_status(job_id)
    if status is None:
        raise HTTPException(404, "job not found")
    return status


def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=True)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _event_type(ev: dict) -> str:
    if ev["status"] == "done":
        return "done"
    if ev["status"] == "failed":
        return "failed"
    return "progress"


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")

    async def event_stream():
        # 先发当前状态快照
        yield _sse(_event_type(queue.current_event(job)), queue.current_event(job))
        if job.status in ("done", "failed"):
            return

        q = queue.subscribe(job_id)
        try:
            # 订阅后复查状态,避免漏掉瞬间完成的终态
            latest = queue.get_job(job_id)
            if latest is not None and latest.status in ("done", "failed"):
                yield _sse(
                    _event_type(queue.current_event(latest)),
                    queue.current_event(latest),
                )
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                etype = _event_type(event)
                yield _sse(etype, event)
                if event["status"] in ("done", "failed"):
                    break
        finally:
            queue.unsubscribe(job_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
