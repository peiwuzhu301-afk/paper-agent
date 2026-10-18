from __future__ import annotations

import json
import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class WorkflowEvent:
    task_id: str
    stage: str
    event: str
    message: str
    data: dict[str, Any]
    ts: float


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[queue.Queue[dict[str, Any]]]] = defaultdict(list)
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(
        self,
        task_id: str,
        stage: str,
        event: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        payload = asdict(
            WorkflowEvent(
                task_id=task_id,
                stage=stage,
                event=event,
                message=message,
                data=data or {},
                ts=time.time(),
            )
        )
        with self._lock:
            self._history[task_id].append(payload)
            self._history[task_id] = self._history[task_id][-500:]
            for listener in list(self._listeners[task_id]):
                try:
                    listener.put_nowait(payload)
                except queue.Full:
                    pass

    def subscribe(self, task_id: str) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._listeners[task_id].append(q)
            for item in self._history.get(task_id, [])[-100:]:
                try:
                    q.put_nowait(item)
                except queue.Full:
                    break
        return q

    def unsubscribe(self, task_id: str, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if q in self._listeners.get(task_id, []):
                self._listeners[task_id].remove(q)

    def history(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history.get(task_id, []))


bus = EventBus()
