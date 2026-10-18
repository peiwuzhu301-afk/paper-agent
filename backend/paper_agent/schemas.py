from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, model_validator

from .config import settings


class PaperRecord(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    full_text: str = ""
    doi: str = ""
    source: str = "sample"


class PaperEvidence(BaseModel):
    paper_id: str
    title: str
    research_question: str = ""
    method: str = ""
    algorithm: str = ""
    formulas: str = ""
    architecture: str = ""
    dataset: str = ""
    experiment_setup: str = ""
    experiment_results: str = ""
    metrics: str = ""
    pros: str = ""
    conclusion: str = ""
    limitations: str = ""
    evidence_quote: str = ""
    evidence_level: str = "摘要"
    url: str = ""


class ReviewResult(BaseModel):
    score: float = 0.0
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    verdict: Literal["pass", "revise"] = "revise"


KNOWN_SOURCES = ("sample", "arxiv", "semantic_scholar", "openalex", "crossref")


class TaskCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    research_question: str = Field(default="", max_length=1000)
    max_papers: int = Field(default=6, ge=2, le=settings.max_papers_ceiling)
    top_k: int = Field(default=5, ge=2, le=settings.top_k_ceiling)
    # 向后兼容：旧的单来源字段。新前端使用 sources 多选。
    source: str = "sample"
    sources: list[str] = Field(default_factory=list)
    report_format: str = settings.default_report_format
    require_human_review: bool = True

    @model_validator(mode="after")
    def _normalize_sources(self) -> "TaskCreate":
        cleaned = [str(item).strip().lower() for item in self.sources if str(item).strip()]
        if not cleaned:
            cleaned = [self.source.strip().lower() or settings.source]
        # 去重并保序；未知来源回退为内置示例，避免静默失败
        seen: list[str] = []
        for name in cleaned:
            resolved = name if name in KNOWN_SOURCES else "sample"
            if resolved not in seen:
                seen.append(resolved)
        self.sources = seen
        self.source = seen[0]
        return self


class ResumeRequest(BaseModel):
    action: Literal["approve", "revise", "reject"]
    feedback: str = Field(default="", max_length=4000)


class TaskSummary(BaseModel):
    task_id: str
    status: str
    stage: str = ""
    topic: str = ""
    research_question: str = ""
    source: str = ""
    sources: list[str] = Field(default_factory=list)
    report_format: str = ""
    report_path: str = ""
    final_report: str = ""
    draft_report: str = ""
    previous_draft: str = ""
    review: dict[str, Any] = Field(default_factory=dict)
    interrupt: dict[str, Any] | None = None
    error: str = ""


class ResearchState(TypedDict):
    task_id: str
    topic: str
    research_question: str
    max_papers: int
    top_k: int
    source: str
    sources: list[str]
    report_format: str
    require_human_review: bool
    status: str
    stage: str
    queries: list[str]
    papers: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    retrieved: list[dict[str, Any]]
    analysis: str
    draft_report: str
    previous_draft: NotRequired[str]
    review: dict[str, Any]
    human_action: str
    human_feedback: str
    revision_round: int
    max_revision_rounds: int
    final_report: str
    report_path: str
    error: str
    metadata: NotRequired[dict[str, Any]]
