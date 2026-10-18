from __future__ import annotations

import asyncio
import queue
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles

from .config import settings
from .docx import markdown_to_docx
from .events import bus
from .html import markdown_to_html
from .pdf import html_to_pdf
from .schemas import ResumeRequest, TaskCreate
from .service import manager
from .utils import slugify


app = FastAPI(title="Paper-Agent API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_token_guard(request, call_next):
    """单一访问口令保护：仅作用于 /api/*，前端静态资源无需认证。"""
    token = settings.access_token
    if token and request.url.path.startswith("/api"):
        provided = (
            request.headers.get("x-access-token")
            or request.query_params.get("token")
            or request.cookies.get("pa_token")
            or ""
        )
        authorization = request.headers.get("authorization", "")
        if not provided and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if provided != token:
            return JSONResponse({"detail": "未授权：访问口令缺失或错误"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "llm_mode": settings.llm_mode,
        "default_source": settings.source,
        "workspace": str(settings.workspace),
    }


@app.post("/api/tasks")
def create_task(request: TaskCreate):
    task_id = manager.create(request)
    return {"task_id": task_id, "status": "queued"}


@app.get("/api/tasks")
def list_tasks(limit: int = 100):
    return {"tasks": manager.list_tasks(limit)}


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    try:
        manager.cancel(task_id)
        return {"task_id": task_id, "status": "cancelling"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/tasks/{task_id}/continue")
def continue_task(task_id: str):
    try:
        manager.continue_from_checkpoint(task_id)
        return {"task_id": task_id, "status": "resuming"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    try:
        return manager.summary(task_id).model_dump()
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@app.get("/api/tasks/{task_id}/history")
def get_history(task_id: str):
    try:
        manager.summary(task_id)
        return {"task_id": task_id, "history": manager.history(task_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str, request: ResumeRequest):
    try:
        manager.resume(task_id, request.action, request.feedback)
        return {"task_id": task_id, "status": "resuming", "action": request.action}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/tasks/{task_id}/report", response_class=PlainTextResponse)
def get_report(task_id: str):
    try:
        return manager.report(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@app.get("/api/tasks/{task_id}/report.docx")
def get_report_docx(task_id: str, variant: str = "auto"):
    """把报告以 Word（.docx）返回，供前端直接下载。"""
    try:
        summary = manager.summary(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    if variant == "draft":
        content = summary.draft_report
    else:  # final / auto
        content = summary.final_report or summary.draft_report
    if not content:
        raise HTTPException(status_code=409, detail="报告尚未生成，请等待写作智能体完成")
    data = markdown_to_docx(content, title=summary.topic)
    filename = f"{task_id}-{slugify(summary.topic) or 'report'}.docx"
    disposition = (
        f'attachment; filename="{task_id}.docx"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": disposition},
    )


def _report_text(summary, variant: str) -> str:
    if variant == "draft":
        return summary.draft_report
    return summary.final_report or summary.draft_report


def _attachment(filename: str, ascii_fallback: str) -> dict[str, str]:
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }


@app.get("/api/tasks/{task_id}/report.html")
def get_report_html(task_id: str, variant: str = "auto"):
    try:
        summary = manager.summary(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    content = _report_text(summary, variant)
    if not content:
        raise HTTPException(status_code=409, detail="报告尚未生成")
    html = markdown_to_html(content, summary.topic)
    filename = f"{task_id}-{slugify(summary.topic) or 'report'}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=_attachment(filename, f"{task_id}.html"),
    )


@app.get("/api/tasks/{task_id}/report.pdf")
def get_report_pdf(task_id: str, variant: str = "auto"):
    try:
        summary = manager.summary(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    content = _report_text(summary, variant)
    if not content:
        raise HTTPException(status_code=409, detail="报告尚未生成")
    try:
        pdf_bytes = html_to_pdf(markdown_to_html(content, summary.topic))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    filename = f"{task_id}-{slugify(summary.topic) or 'report'}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=_attachment(filename, f"{task_id}.pdf"),
    )


def _ensure_task_exists(task_id: str) -> None:
    try:
        manager.summary(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@app.get("/api/tasks/{task_id}/events", response_class=EventSourceResponse)
async def task_events(task_id: str, _: None = Depends(_ensure_task_exists)):
    # FastAPI's SSE support requires this path operation to be an async generator
    # that yields ServerSentEvent objects; returning an EventSourceResponse
    # instance here would be iterated as a plain object and fail.
    q = bus.subscribe(task_id)
    counter = 0
    try:
        while True:
            try:
                item = await asyncio.to_thread(q.get, True, 1.0)
                counter += 1
                yield ServerSentEvent(data=item, event=item.get("event", "message"), id=str(counter))
                if item.get("event") in {"failed"} or item.get("stage") in {"finalize", "rejected"}:
                    break
            except queue.Empty:
                summary = manager.summary(task_id)
                if summary.status in {"completed", "rejected", "failed"}:
                    yield ServerSentEvent(
                        data={"task_id": task_id, "status": summary.status},
                        event="done",
                        id=str(counter + 1),
                    )
                    break
                yield ServerSentEvent(comment="keep-alive")
    finally:
        bus.unsubscribe(task_id, q)


frontend_dist = settings.frontend_dist
if settings.serve_frontend and frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
