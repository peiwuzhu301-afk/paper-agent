from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any


def timestamp_id() -> str:
    """以时间命名任务号，便于记忆：YYYYMMDD-HHMMSS。"""
    return time.strftime("%Y%m%d-%H%M%S")


def slugify(value: str, max_len: int = 70) -> str:
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return (text[:max_len] or "research").lower()


def stable_hash(text: str, length: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def hash_embedding(text: str, dim: int = 256) -> list[float]:
    """Small deterministic feature-hashing embedding with no model download.

    This is intentionally lightweight for a zero-key demo. Replace it with a production
    embedding model if you need higher retrieval quality.
    """
    vec = [0.0] * dim
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _repair_json(text: str) -> str:
    """尽力修复模型输出的常见 JSON 瑕疵（尾逗号、未加引号的键、代码块围栏）。"""
    fixed = text.strip()
    fixed = re.sub(r"^```(?:json)?\s*|\s*```$", "", fixed, flags=re.I | re.S).strip()
    fixed = re.sub(r",(\s*[}\]])", r"\1", fixed)  # 去掉尾逗号
    fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', fixed)  # 未加引号的键
    return fixed


def extract_json_object(text: Any) -> dict[str, Any]:
    """从模型输出中稳健地提取一个 JSON 对象。

    依次尝试：直接解析 → 代码块围栏内 → 首个 {...} 片段 → 修复后解析 →
    ``ast.literal_eval``（可处理单引号/Python 字面量）。全部失败才抛错。
    """
    raw = "" if text is None else str(text).strip()
    if not raw:
        raise json.JSONDecodeError("模型输出为空", raw, 0)

    candidates: list[str] = [raw]
    if raw.startswith("```"):
        candidates.append(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip())
    block = re.search(r"\{.*\}", raw, re.S)
    if block:
        candidates.append(block.group(0))

    for candidate in candidates:
        for attempt in (candidate, _repair_json(candidate)):
            try:
                data = json.loads(attempt)
            except (json.JSONDecodeError, TypeError, ValueError):
                data = None
            if isinstance(data, dict):
                return data
            try:
                literal = ast.literal_eval(attempt)
            except (ValueError, SyntaxError, TypeError):
                literal = None
            if isinstance(literal, dict):
                return literal

    raise json.JSONDecodeError("无法从模型输出解析出 JSON 对象", raw, 0)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
