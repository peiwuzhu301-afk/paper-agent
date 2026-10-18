from __future__ import annotations

import json
from pathlib import Path

from .config import settings
from .sample_data import SAMPLE_PAPERS
from .utils import hash_embedding


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def run_sample_retrieval_benchmark(top_k: int = 5) -> dict:
    cases = json.loads((settings.project_root / "data" / "eval_cases.json").read_text(encoding="utf-8"))
    paper_vectors = {
        item["paper_id"]: hash_embedding(f"{item['title']} {item['abstract']}") for item in SAMPLE_PAPERS
    }
    hits = 0
    rows = []
    for case in cases:
        qv = hash_embedding(case["query"])
        ranked = sorted(
            ((pid, cosine(qv, vec)) for pid, vec in paper_vectors.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        predicted = [pid for pid, _ in ranked[:top_k]]
        relevant = set(case["relevant_paper_ids"])
        hit = bool(relevant.intersection(predicted))
        hits += int(hit)
        rows.append({"query": case["query"], "top_k": predicted, "relevant": sorted(relevant), "hit": hit})
    return {
        "metric": f"Hit@{top_k}",
        "value": round(hits / max(1, len(cases)), 4),
        "cases": len(cases),
        "details": rows,
        "note": "Tiny bundled sanity benchmark; do not use this number as a resume metric.",
    }
