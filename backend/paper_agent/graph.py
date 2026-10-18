from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings
from . import control
from .events import bus
from .llm import AgentSuite
from .rag import EvidenceStore
from .schemas import PaperEvidence, PaperRecord, ResearchState
from .sources import build_sources, fetch_full_text
from .utils import slugify, write_json


_SECTION_KEYWORDS = (
    "method", "approach", "architecture", "model", "network", "algorithm", "framework",
    "formula", "equation", "training", "objective", "loss",
    "experiment", "evaluation", "result", "ablation", "dataset", "baseline", "benchmark",
    "方法", "算法", "模型", "架构", "网络", "公式", "训练", "损失",
    "实验", "评估", "结果", "消融", "数据集", "基线",
)


def _select_relevant_text(text: str, budget: int) -> str:
    """全文超长时，优先保留含方法/算法/公式/实验关键词的片段。"""
    if not text or len(text) <= budget:
        return text
    lines = text.splitlines()
    chunk_size = 40
    chunks: list[tuple[int, int, str]] = []
    for start in range(0, len(lines), chunk_size):
        block = "\n".join(lines[start : start + chunk_size])
        lowered = block.lower()
        score = sum(1 for keyword in _SECTION_KEYWORDS if keyword in lowered)
        chunks.append((score, start, block))
    selected: list[tuple[int, str]] = []
    used = 0
    for _, start, block in sorted(chunks, key=lambda item: -item[0]):
        if used + len(block) > budget:
            continue
        selected.append((start, block))
        used += len(block)
        if used >= budget:
            break
    selected.sort()
    return "\n\n".join(block for _, block in selected)[:budget]


class PaperAgentWorkflow:
    def __init__(self) -> None:
        settings.ensure_dirs()
        self.conn = sqlite3.connect(settings.checkpoint_db, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.conn)
        self.agents = AgentSuite()
        self.evidence_store = EvidenceStore()
        self.graph = self._build_graph()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _emit(self, state: ResearchState, stage: str, event: str, message: str, **data: Any) -> None:
        bus.publish(state["task_id"], stage, event, message, data)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
    def search_node(self, state: ResearchState) -> dict[str, Any]:
        self._emit(state, "search", "start", "SearchAgent is planning scholarly queries")
        queries = self.agents.expand_queries(state["topic"], state["research_question"])
        source = build_sources(state.get("sources") or [state.get("source", settings.source)])
        papers = source.search(queries, state["max_papers"])
        for error in getattr(source, "errors", []):
            self._emit(state, "search", "warning", f"数据源检索失败（已跳过）：{error}")
        payload = [paper.model_dump() for paper in papers]
        self._emit(
            state,
            "search",
            "complete",
            f"SearchAgent found {len(payload)} candidate papers",
            queries=queries,
            paper_titles=[p["title"] for p in payload],
            sources=sorted({p["source"] for p in payload}),
        )
        return {"queries": queries, "papers": payload, "stage": "search", "status": "running"}

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    def read_node(self, state: ResearchState) -> dict[str, Any]:
        self._emit(state, "read", "start", "ReaderAgent is extracting structured evidence")
        task_dir = settings.task_papers_dir(state["task_id"])
        allow_download = settings.download_pdfs or settings.arxiv_download_pdfs
        papers = state["papers"]
        total = len(papers)
        research_question = state["research_question"]

        def process(item: tuple[int, dict[str, Any]]) -> tuple[int, PaperEvidence, bool, str | None]:
            index, raw = item
            control.raise_if_cancelled(state["task_id"])
            paper = PaperRecord(**raw)
            full_text = ""
            error: str | None = None
            if allow_download and paper.pdf_url:
                try:
                    destination = task_dir / f"{paper.paper_id}-{slugify(paper.title, 40)}.pdf"
                    full_text = fetch_full_text(
                        paper.pdf_url,
                        dest_path=destination,
                        max_chars=settings.reader_max_chars,
                        max_bytes=settings.pdf_max_bytes,
                    )
                except Exception as exc:  # noqa: BLE001 - 下载失败回退摘要
                    error = str(exc)
            paper.full_text = full_text
            source_text = _select_relevant_text(
                full_text or paper.abstract or "", settings.reader_max_chars
            )
            evidence_item = self.agents.extract_evidence(paper, research_question, source_text)
            evidence_item.evidence_level = "全文" if full_text else "摘要"
            return index, evidence_item, bool(full_text), error

        results: dict[int, PaperEvidence] = {}
        workers = max(1, min(settings.max_concurrency, total or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process, (index, raw)): index for index, raw in enumerate(papers)}
            for done, future in enumerate(as_completed(futures), start=1):
                control.raise_if_cancelled(state["task_id"])
                try:
                    index, evidence_item, used_full, error = future.result()
                except Exception as exc:  # noqa: BLE001 - 单篇失败不影响整体
                    raw = papers[futures[future]]
                    paper_id = raw.get("paper_id", "?")
                    self._emit(
                        state, "read", "warning", f"{paper_id} 精读失败，已跳过",
                        error=str(exc), progress=f"{done}/{total}",
                    )
                    continue
                results[index] = evidence_item
                if error:
                    self._emit(
                        state, "read", "warning",
                        f"{evidence_item.paper_id} 全文下载失败，改用摘要",
                        error=error, progress=f"{done}/{total}",
                    )
                origin = "全文" if used_full else "摘要"
                self._emit(
                    state, "read", "paper",
                    f"已精读 {evidence_item.paper_id}（{origin}）：{evidence_item.title}",
                    progress=f"{done}/{total}",
                )

        evidence = [results[index] for index in sorted(results)]
        self.evidence_store.upsert(state["task_id"], evidence)
        full_count = sum(1 for item in evidence if item.evidence_level == "全文")
        abstract_only = [item.paper_id for item in evidence if item.evidence_level != "全文"]
        self._emit(
            state, "read", "complete",
            f"Stored {len(evidence)} evidence records in ChromaDB",
            coverage=f"全文 {full_count} / 摘要 {len(evidence) - full_count}",
            abstract_only=abstract_only,
        )
        return {"evidence": [e.model_dump() for e in evidence], "stage": "read"}

    def analyze_node(self, state: ResearchState) -> dict[str, Any]:
        self._emit(state, "analyze", "start", "AnalystAgent is retrieving Top-K evidence and synthesizing gaps")
        query = f"{state['topic']} {state['research_question']} methods datasets metrics limitations"
        retrieved = self.evidence_store.query(state["task_id"], query, state["top_k"])
        analysis = self.agents.analyze(state["topic"], state["research_question"], retrieved)
        self._emit(
            state,
            "analyze",
            "complete",
            f"AnalystAgent synthesized {len(retrieved)} retrieved evidence items",
            retrieved=[r.get("paper_id") for r in retrieved],
        )
        return {"retrieved": retrieved, "analysis": analysis, "stage": "analyze"}

    def write_node(self, state: ResearchState) -> dict[str, Any]:
        self._emit(state, "write", "start", "WriterAgent is drafting the report")
        evidence = [PaperEvidence(**item) for item in state["evidence"]]
        draft = self.agents.write_report(
            state["topic"],
            state["research_question"],
            evidence,
            state["analysis"],
            state.get("human_feedback", ""),
            state.get("draft_report", ""),
            state.get("report_format", settings.default_report_format),
            lambda message: self._emit(state, "write", "start", message),
        )
        revision_round = state.get("revision_round", 0)
        if state.get("human_feedback"):
            revision_round += 1
        self._emit(
            state,
            "write",
            "complete",
            f"WriterAgent produced draft revision {revision_round}",
            chars=len(draft),
        )
        return {
            "draft_report": draft,
            "previous_draft": state.get("draft_report", ""),
            "stage": "write",
            "status": "running",
            "revision_round": revision_round,
            "human_feedback": "",
        }

    def review_node(self, state: ResearchState) -> dict[str, Any]:
        self._emit(state, "review", "start", "ReviewerAgent is auditing citations and unsupported claims")
        evidence = [PaperEvidence(**item) for item in state["evidence"]]
        review = self.agents.review_report(state["draft_report"], evidence)
        status = "awaiting_review" if state["require_human_review"] else "running"
        self._emit(
            state,
            "review",
            "complete",
            f"ReviewerAgent score: {review.score}/5 ({review.verdict})",
            review=review.model_dump(),
            human_review=state["require_human_review"],
        )
        return {"review": review.model_dump(), "stage": "review", "status": status}

    def human_gate_node(self, state: ResearchState) -> dict[str, Any]:
        if not state["require_human_review"]:
            self._emit(state, "human_review", "auto_approve", "Human review disabled; continuing automatically")
            return {"human_action": "approve", "status": "running", "stage": "human_review"}

        payload = {
            "type": "paper_agent_review",
            "task_id": state["task_id"],
            "message": "Review the generated report. Approve, request a revision, or reject the task.",
            "review": state["review"],
            "draft_report": state["draft_report"],
            "revision_round": state.get("revision_round", 0),
            "max_revision_rounds": state.get("max_revision_rounds", 2),
        }
        self._emit(state, "human_review", "interrupt", "Workflow paused for human review")
        decision = interrupt(payload)
        if not isinstance(decision, dict):
            decision = {"action": "approve", "feedback": ""}
        action = str(decision.get("action", "approve"))
        feedback = str(decision.get("feedback", ""))
        if action == "revise" and state.get("revision_round", 0) >= state.get("max_revision_rounds", 2):
            action = "reject"
            feedback = (feedback + " Maximum revision rounds reached.").strip()
        self._emit(state, "human_review", "resume", f"Human decision: {action}", feedback=feedback)
        return {
            "human_action": action,
            "human_feedback": feedback,
            "status": "running",
            "stage": "human_review",
        }

    def rejected_node(self, state: ResearchState) -> dict[str, Any]:
        self._emit(state, "rejected", "complete", "Task rejected by human reviewer")
        self._save_run_snapshot(state, status="rejected")
        return {"status": "rejected", "stage": "rejected", "final_report": ""}

    def finalize_node(self, state: ResearchState) -> dict[str, Any]:
        report = state["draft_report"]
        filename = f"{state['task_id']}-{slugify(state['topic'])}.md"
        path = settings.reports_dir / filename
        path.write_text(report, encoding="utf-8")
        self._save_run_snapshot({**state, "report_path": str(path)}, status="completed")
        self._emit(state, "finalize", "complete", f"Final report saved to {path}", report_path=str(path))
        return {
            "final_report": report,
            "report_path": str(path),
            "status": "completed",
            "stage": "finalize",
        }

    def _save_run_snapshot(self, state: dict[str, Any], status: str) -> None:
        safe_state = dict(state)
        safe_state["status"] = status
        write_json(settings.runs_dir / f"{state['task_id']}.json", safe_state)

    @staticmethod
    def route_after_human(state: ResearchState) -> Literal["write", "finalize", "rejected"]:
        action = state.get("human_action", "approve")
        if action == "revise":
            return "write"
        if action == "reject":
            return "rejected"
        return "finalize"

    def _build_graph(self):
        workflow = StateGraph(ResearchState)
        workflow.add_node("search", self.search_node)
        workflow.add_node("read", self.read_node)
        workflow.add_node("analyze", self.analyze_node)
        workflow.add_node("write", self.write_node)
        workflow.add_node("review", self.review_node)
        workflow.add_node("human_gate", self.human_gate_node)
        workflow.add_node("rejected", self.rejected_node)
        workflow.add_node("finalize", self.finalize_node)

        workflow.add_edge(START, "search")
        workflow.add_edge("search", "read")
        workflow.add_edge("read", "analyze")
        workflow.add_edge("analyze", "write")
        workflow.add_edge("write", "review")
        workflow.add_edge("review", "human_gate")
        workflow.add_conditional_edges(
            "human_gate",
            self.route_after_human,
            {"write": "write", "finalize": "finalize", "rejected": "rejected"},
        )
        workflow.add_edge("finalize", END)
        workflow.add_edge("rejected", END)
        return workflow.compile(checkpointer=self.checkpointer)

    def initial_state(self, task_id: str, payload: dict[str, Any]) -> ResearchState:
        topic = payload["topic"].strip()
        question = payload.get("research_question", "").strip() or f"What are the main methods, evidence, limitations, and open questions for {topic}?"
        sources = [str(item).strip().lower() for item in (payload.get("sources") or []) if str(item).strip()]
        if not sources:
            fallback = str(payload.get("source") or settings.source).strip().lower()
            sources = [fallback] if fallback else [settings.source]
        report_format = str(payload.get("report_format") or settings.default_report_format).strip().lower()
        return ResearchState(
            task_id=task_id,
            topic=topic,
            research_question=question,
            max_papers=int(payload.get("max_papers", settings.default_max_papers)),
            top_k=int(payload.get("top_k", settings.default_top_k)),
            source=sources[0],
            sources=sources,
            report_format=report_format,
            require_human_review=bool(payload.get("require_human_review", settings.default_human_review)),
            status="running",
            stage="created",
            queries=[],
            papers=[],
            evidence=[],
            retrieved=[],
            analysis="",
            draft_report="",
            review={},
            human_action="",
            human_feedback="",
            revision_round=0,
            max_revision_rounds=2,
            final_report="",
            report_path="",
            error="",
        )

    def run(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = {"configurable": {"thread_id": task_id}, "recursion_limit": 30}
        state = self.initial_state(task_id, payload)
        return self.graph.invoke(state, config=config)

    def resume(self, task_id: str, action: str, feedback: str = "") -> dict[str, Any]:
        config = {"configurable": {"thread_id": task_id}, "recursion_limit": 30}
        return self.graph.invoke(Command(resume={"action": action, "feedback": feedback}), config=config)

    def continue_run(self, task_id: str) -> dict[str, Any]:
        """从最近一次检查点继续执行（不重新跑已完成的节点）。"""
        config = {"configurable": {"thread_id": task_id}, "recursion_limit": 30}
        return self.graph.invoke(None, config=config)

    def get_state(self, task_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        config = {"configurable": {"thread_id": task_id}}
        snapshot = self.graph.get_state(config)
        values = dict(snapshot.values or {})
        interrupt_payload = None
        for task in snapshot.tasks or ():
            if getattr(task, "interrupts", None):
                first = task.interrupts[0]
                interrupt_payload = getattr(first, "value", None)
                break
        return values, interrupt_payload

    def state_history(self, task_id: str, limit: int = 20) -> list[dict[str, Any]]:
        config = {"configurable": {"thread_id": task_id}}
        history: list[dict[str, Any]] = []
        for idx, snapshot in enumerate(self.graph.get_state_history(config)):
            if idx >= limit:
                break
            history.append(
                {
                    "created_at": str(getattr(snapshot, "created_at", "")),
                    "next": list(getattr(snapshot, "next", ()) or ()),
                    "values": dict(snapshot.values or {}),
                }
            )
        return history
