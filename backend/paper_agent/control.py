from __future__ import annotations

import threading


class TaskCancelled(Exception):
    """用户取消任务时抛出，用于中止后台工作线程。"""


_cancelled: set[str] = set()
_lock = threading.Lock()


def request_cancel(task_id: str) -> None:
    with _lock:
        _cancelled.add(task_id)


def is_cancelled(task_id: str) -> bool:
    with _lock:
        return task_id in _cancelled


def clear(task_id: str) -> None:
    with _lock:
        _cancelled.discard(task_id)


def raise_if_cancelled(task_id: str) -> None:
    if is_cancelled(task_id):
        raise TaskCancelled(task_id)
