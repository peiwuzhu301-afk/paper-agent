from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import settings
from .utils import read_json


SECTION_ALIASES: dict[str, list[str]] = {
    "Executive Summary": ["Executive Summary", "摘要"],
    "Research Question": ["Research Question", "研究问题"],
    "Evidence Map": ["Evidence Map", "证据映射"],
    "Methods and Approaches": ["Methods and Approaches", "方法与技术路线", "方法"],
    "Dataset and Evaluation": ["Dataset and Evaluation", "数据集与评估", "实验与结果", "评估"],
    "Key Findings": ["Key Findings", "关键发现", "结果与讨论"],
    "Contradictions and Limitations": ["Contradictions and Limitations", "矛盾与局限", "局限"],
    "Open Questions": ["Open Questions", "开放问题", "讨论"],
    "References": ["References", "参考文献"],
}
REQUIRED_SECTIONS = list(SECTION_ALIASES)


def evaluate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    papers = snapshot.get("papers", []) or []
    evidence = snapshot.get("evidence", []) or []
    report = snapshot.get("final_report") or snapshot.get("draft_report") or ""
    paper_ids = [str(item.get("paper_id", "")) for item in evidence]
    cited = [pid for pid in paper_ids if pid and f"[{pid}]" in report]
    section_hits = [
        section
        for section, variants in SECTION_ALIASES.items()
        if any(f"## {variant}" in report for variant in variants)
    ]
    return {
        "papers_found": len(papers),
        "structured_evidence_records": len(evidence),
        "structured_parse_rate": round(len(evidence) / max(1, len(papers)), 4),
        "citation_coverage": round(len(cited) / max(1, len(paper_ids)), 4),
        "section_coverage": round(len(section_hits) / len(REQUIRED_SECTIONS), 4),
        "reviewer_score": (snapshot.get("review") or {}).get("score"),
        "reviewer_verdict": (snapshot.get("review") or {}).get("verdict"),
        "report_chars": len(report),
    }


def evaluate_task(task_id: str) -> dict[str, Any]:
    path = settings.runs_dir / f"{task_id}.json"
    snapshot = read_json(path)
    if not snapshot:
        raise FileNotFoundError(path)
    return evaluate_snapshot(snapshot)
