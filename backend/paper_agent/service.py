from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .config import settings
from . import control
from .events import bus
from .graph import PaperAgentWorkflow
from .schemas import TaskCreate, TaskSummary
from .utils import read_json, timestamp_id, write_json


class TaskManager:
    def __init__(self) -> None:
        self.workflow = PaperAgentWorkflow()
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._recover_orphans()

    def _recover_orphans(self) -> None:
        """后端重启会丢失后台线程，把残留的“进行中”任务标记为已中断，避免永久卡在运行中。"""
        for meta_path in settings.runs_dir.glob("*.meta.json"):
            try:
                meta = read_json(meta_path, {}) or {}
            except Exception:  # noqa: BLE001
                continue
            if meta.get("status") in {"running", "queued", "resuming", "cancelling"}:
                meta["status"] = "interrupted"
                meta["error"] = meta.get("error") or "服务重启导致任务中断"
                write_json(meta_path, meta)

    def _new_task_id(self) -> str:
        base = timestamp_id()
        candidate = base
        suffix = 1
        while (settings.runs_dir / f"{candidate}.meta.json").exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def _meta_path(self, task_id: str) -> Path:
        return settings.runs_dir / f"{task_id}.meta.json"

    def _write_meta(self, task_id: str, payload: dict[str, Any]) -> None:
        current = read_json(self._meta_path(task_id), {}) or {}
        current.update(payload)
        current["task_id"] = task_id
        write_json(self._meta_path(task_id), current)

    def create(self, request: TaskCreate) -> str:
        task_id = self._new_task_id()
        payload = request.model_dump()
        self._write_meta(task_id, {**payload, "status": "queued", "stage": "created", "error": ""})
        bus.publish(task_id, "created", "queued", "Task created and queued", payload)
        self._spawn(task_id, self._run_start, payload)
        return task_id

    def _spawn(self, task_id: str, target, *args) -> None:
        thread = threading.Thread(target=target, args=(task_id, *args), daemon=True)
        with self._lock:
            self._threads[task_id] = thread
        thread.start()

    def _run_start(self, task_id: str, payload: dict[str, Any]) -> None:
        self._write_meta(task_id, {"status": "running"})
        try:
            result = self.workflow.run(task_id, payload)
            self._after_run(task_id, result)
        except control.TaskCancelled:
            self._mark_cancelled(task_id)
        except Exception as exc:
            self._fail(task_id, exc)
        finally:
            control.clear(task_id)

    def _run_resume(self, task_id: str, action: str, feedback: str) -> None:
        self._write_meta(task_id, {"status": "running"})
        try:
            result = self.workflow.resume(task_id, action, feedback)
            self._after_run(task_id, result)
        except control.TaskCancelled:
            self._mark_cancelled(task_id)
        except Exception as exc:
            self._fail(task_id, exc)
        finally:
            control.clear(task_id)

    def _mark_cancelled(self, task_id: str) -> None:
        self._write_meta(task_id, {"status": "cancelled", "stage": "cancelled"})
        bus.publish(task_id, "cancelled", "failed", "任务已被取消")

    def _after_run(self, task_id: str, result: dict[str, Any]) -> None:
        values, interrupt_payload = self.workflow.get_state(task_id)
        if interrupt_payload:
            self._write_meta(task_id, {"status": "awaiting_review", "stage": values.get("stage", "review")})
            return
        status = values.get("status") or result.get("status") or "completed"
        self._write_meta(
            task_id,
            {
                "status": status,
                "stage": values.get("stage", result.get("stage", "")),
                "report_path": values.get("report_path", result.get("report_path", "")),
            },
        )

    def _fail(self, task_id: str, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"
        self._write_meta(task_id, {"status": "failed", "stage": "error", "error": error})
        bus.publish(task_id, "error", "failed", "Workflow failed", {"error": error})
        try:
            self.workflow.graph.update_state(
                {"configurable": {"thread_id": task_id}},
                {"status": "failed", "stage": "error", "error": error},
            )
        except Exception:
            pass

    def resume(self, task_id: str, action: str, feedback: str = "") -> None:
        values, interrupt_payload = self.workflow.get_state(task_id)
        if not values:
            raise KeyError(task_id)
        if not interrupt_payload:
            raise ValueError("Task is not waiting for human review.")
        self._spawn(task_id, self._run_resume, action, feedback)

    def continue_from_checkpoint(self, task_id: str) -> None:
        """从最近一次检查点继续执行（用于服务重启/瞬时失败后恢复）。"""
        values, interrupt_payload = self.workflow.get_state(task_id)
        if not values:
            raise KeyError(task_id)
        if interrupt_payload:
            raise ValueError("任务正在等待人工审核，请使用审核（通过/修改/驳回）操作恢复。")
        if values.get("status") in {"completed", "rejected"}:
            raise ValueError("任务已结束，无法继续。")
        self._spawn(task_id, self._run_continue)

    def _run_continue(self, task_id: str) -> None:
        self._write_meta(task_id, {"status": "running", "error": ""})
        try:
            result = self.workflow.continue_run(task_id)
            self._after_run(task_id, result)
        except control.TaskCancelled:
            self._mark_cancelled(task_id)
        except Exception as exc:
            self._fail(task_id, exc)
        finally:
            control.clear(task_id)

    def summary(self, task_id: str) -> TaskSummary:
        meta = read_json(self._meta_path(task_id), {}) or {}
        try:
            values, interrupt_payload = self.workflow.get_state(task_id)
        except Exception:
            values, interrupt_payload = {}, None
        if not meta and not values:
            raise KeyError(task_id)
        merged = {**meta, **values}
        if interrupt_payload:
            merged["status"] = "awaiting_review"
        return TaskSummary(
            task_id=task_id,
            status=merged.get("status", "unknown"),
            stage=merged.get("stage", ""),
            topic=merged.get("topic", ""),
            research_question=merged.get("research_question", ""),
            source=merged.get("source", ""),
            sources=merged.get("sources", []) or [],
            report_format=merged.get("report_format", ""),
            report_path=merged.get("report_path", ""),
            final_report=merged.get("final_report", ""),
            draft_report=merged.get("draft_report", ""),
            previous_draft=merged.get("previous_draft", ""),
            review=merged.get("review", {}) or {},
            interrupt=interrupt_payload,
            error=merged.get("error", ""),
        )

    def report(self, task_id: str) -> str:
        summary = self.summary(task_id)
        if summary.final_report:
            return summary.final_report
        if summary.report_path and Path(summary.report_path).exists():
            return Path(summary.report_path).read_text(encoding="utf-8")
        return summary.draft_report

    def history(self, task_id: str) -> list[dict[str, Any]]:
        return self.workflow.state_history(task_id)

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for meta_path in settings.runs_dir.glob("*.meta.json"):
            try:
                meta = read_json(meta_path, {}) or {}
            except Exception:  # noqa: BLE001
                continue
            task_id = str(meta.get("task_id") or meta_path.name.split(".")[0])
            sources = meta.get("sources")
            if not sources and meta.get("source"):
                sources = [meta["source"]]
            items.append(
                {
                    "task_id": task_id,
                    "status": meta.get("status", "unknown"),
                    "stage": meta.get("stage", ""),
                    "topic": meta.get("topic", ""),
                    "sources": sources or [],
                    "report_format": meta.get("report_format", ""),
                    "has_report": bool(meta.get("report_path")),
                    "updated_at": meta_path.stat().st_mtime,
                }
            )
        items.sort(key=lambda row: row["updated_at"], reverse=True)
        return items[:limit]

    def cancel(self, task_id: str) -> None:
        meta = read_json(self._meta_path(task_id), {}) or {}
        if not meta:
            try:
                values, _ = self.workflow.get_state(task_id)
            except Exception:  # noqa: BLE001
                values = {}
            if not values:
                raise KeyError(task_id)
        control.request_cancel(task_id)
        self._write_meta(task_id, {"status": "cancelling"})


manager = TaskManager()
