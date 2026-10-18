from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

from .config import settings
from .prompts import (
    ANALYST_SYSTEM,
    DETERMINISTIC_SECTIONS,
    OUTLINE_SYSTEM,
    PAPER_DETAIL_SECTIONS,
    READER_SYSTEM,
    REVIEWER_SYSTEM,
    SEARCH_SYSTEM,
    SECTION_HINTS,
    format_label,
    format_spec,
    writer_system,
)
from .schemas import PaperEvidence, PaperRecord, ReviewResult
from .utils import extract_json_object


class AgentSuite:
    """Five-role agent façade.

    ``mock`` mode gives a no-key deterministic demo. ``autogen`` mode uses Microsoft's
    AutoGen AgentChat AssistantAgent for the five specialist roles while LangGraph remains
    the outer workflow/state machine.
    """

    def __init__(self, mode: str | None = None) -> None:
        self.mode = (mode or settings.llm_mode).lower()

    def _autogen_text(
        self,
        name: str,
        system_message: str,
        task: str,
        max_tokens: int | None = None,
    ) -> str:
        async def run() -> str:
            from autogen_core.models import SystemMessage, UserMessage
            from autogen_ext.models.openai import OpenAIChatCompletionClient

            kwargs: dict[str, Any] = {
                "model": settings.openai_model,
                "api_key": settings.openai_api_key or "placeholder",
                "temperature": 0.2,
                "parallel_tool_calls": False,
            }
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
                kwargs["model_info"] = {
                    "vision": settings.model_supports_vision,
                    "function_calling": settings.model_supports_function_calling,
                    "json_output": settings.model_supports_json,
                    "family": "unknown",
                    "structured_output": settings.model_supports_structured_output,
                }
            elif not settings.openai_api_key:
                raise RuntimeError(
                    "PAPER_AGENT_LLM_MODE=autogen requires OPENAI_API_KEY or an OPENAI_BASE_URL. "
                    "Use PAPER_AGENT_LLM_MODE=mock for the zero-key demo."
                )

            client = OpenAIChatCompletionClient(**kwargs)
            try:
                extra: dict[str, Any] = {}
                if max_tokens:
                    extra["max_tokens"] = max_tokens
                messages = [
                    SystemMessage(content=system_message),
                    UserMessage(content=task, source="user"),
                ]
                last_error: Exception | None = None
                attempts = max(1, settings.llm_max_retries)
                for attempt in range(attempts):
                    try:
                        result = await client.create(messages=messages, extra_create_args=extra)
                        content = result.content
                        return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                    except Exception as exc:  # noqa: BLE001 - 瞬时网络/连接错误重试
                        last_error = exc
                        if attempt + 1 >= attempts:
                            break
                        await asyncio.sleep(min(2 ** attempt, 8))
                raise last_error if last_error else RuntimeError("LLM 调用失败")
            finally:
                await client.close()

        return asyncio.run(run())

    @staticmethod
    def _fallback_queries(topic: str, research_question: str) -> list[str]:
        base = (research_question or "").strip() or topic.strip()
        return [
            base,
            f"{topic} methods architecture evaluation",
            f"{topic} limitations comparison benchmark",
        ]

    def expand_queries(self, topic: str, research_question: str) -> list[str]:
        if self.mode == "autogen":
            try:
                raw = self._autogen_text(
                    "search_agent",
                    SEARCH_SYSTEM,
                    f"Topic: {topic}\nResearch question: {research_question or topic}",
                )
                data = extract_json_object(raw)
                queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
                if queries:
                    return queries[:3]
            except Exception:  # noqa: BLE001 - 解析失败则回退到默认检索式
                pass
        return self._fallback_queries(topic, research_question)

    def extract_evidence(
        self,
        paper: PaperRecord,
        research_question: str,
        source_text: str | None = None,
    ) -> PaperEvidence:
        if source_text is not None:
            text = source_text
        else:
            text = paper.full_text.strip() or paper.abstract.strip()
        if self.mode == "autogen":
            try:
                raw = self._autogen_text(
                    "reader_agent",
                    READER_SYSTEM,
                    (
                        f"Research question: {research_question}\nPaper ID: {paper.paper_id}\n"
                        f"Title: {paper.title}\nURL: {paper.url}\nText:\n{text[:48000]}"
                    ),
                )
                data = extract_json_object(raw)
            except Exception:  # noqa: BLE001 - 解析失败则以空字段兜底，不中断整单
                data = {}
            return PaperEvidence(
                paper_id=paper.paper_id,
                title=paper.title,
                research_question=str(data.get("research_question", research_question)),
                method=str(data.get("method", "")),
                algorithm=str(data.get("algorithm", "")),
                formulas=str(data.get("formulas", "")),
                architecture=str(data.get("architecture", "")),
                dataset=str(data.get("dataset", "")),
                experiment_setup=str(data.get("experiment_setup", "")),
                experiment_results=str(data.get("experiment_results", "")),
                metrics=str(data.get("metrics", "")),
                pros=str(data.get("pros", "")),
                conclusion=str(data.get("conclusion", "")),
                limitations=str(data.get("limitations", "")),
                evidence_quote=str(data.get("evidence_quote", "")),
                url=paper.url,
            )

        text = text or "No abstract available."
        first_sentence = re.split(r"(?<=[.!?。！？])\s+", text)[0][:400]
        lower = text.lower()
        method_terms = [
            term
            for term in [
                "retrieval", "multi-agent", "agent", "reasoning", "feedback", "refinement",
                "conversation", "tool", "memory", "evaluation", "generation"
            ]
            if term in lower
        ]
        method = ", ".join(method_terms[:6]) or "Method details should be read from the paper."
        return PaperEvidence(
            paper_id=paper.paper_id,
            title=paper.title,
            research_question=research_question,
            method=method,
            dataset="Not reliably available in the bundled abstract; verify in full text.",
            metrics="Not reliably available in the bundled abstract; verify in full text.",
            conclusion=first_sentence,
            limitations="Demo extraction is abstract-only unless PDF download is enabled.",
            evidence_quote=first_sentence,
            url=paper.url,
        )

    def analyze(self, topic: str, research_question: str, retrieved: list[dict[str, Any]]) -> str:
        evidence_text = "\n\n".join(
            f"[{item.get('paper_id')}] {item.get('title')}\n{item.get('document')}" for item in retrieved
        )
        if self.mode == "autogen":
            return self._autogen_text(
                "analyst_agent",
                ANALYST_SYSTEM,
                f"Topic: {topic}\nResearch question: {research_question}\nEvidence:\n{evidence_text}",
            )
        ids = [item.get("paper_id", "") for item in retrieved]
        cited = ", ".join(f"[{x}]" for x in ids if x)
        return (
            f"检索到的证据 {cited} 指向三个反复出现的工程思路："
            "把生成建立在外部证据之上、把复杂工作拆解为显式的智能体/工作流角色、"
            "在接受产出之前加入反馈或校验回路。证据同时显示，工作流的可控性与模型的自主性之间存在取舍。"
            "由于零密钥演示使用摘要与轻量向量检索，涉及数据集/指标的对比在使用前必须回溯原始论文核实。"
        )

    def write_report(
        self,
        topic: str,
        research_question: str,
        evidence: list[PaperEvidence],
        analysis: str,
        human_feedback: str = "",
        previous_draft: str = "",
        report_format: str = "general",
        on_progress: Callable[[str], None] | None = None,
    ) -> str:
        if self.mode == "autogen":
            return self._autogen_long_report(
                topic,
                research_question,
                evidence,
                analysis,
                human_feedback,
                previous_draft,
                report_format,
                on_progress,
            )

        refs = "\n".join(f"- [{e.paper_id}] [{e.title}]({e.url})" for e in evidence)
        map_rows = "\n".join(
            f"| {e.paper_id} | {e.title.replace('|', '/')} | {e.method.replace('|', '/')} | {e.conclusion.replace('|', '/')[:140]} |"
            for e in evidence
        )
        limitations = "\n".join(f"- [{e.paper_id}] {e.limitations}" for e in evidence)
        revision_note = f"\n> 已纳入人工反馈：{human_feedback}\n" if human_feedback else ""
        return f"""# Paper-Agent 调研报告：{topic}

> 版式：{format_label(report_format)}

## 摘要
{analysis}
{revision_note}
## 研究问题
{research_question or topic}

## 证据映射
| 论文 | 标题 | 方法信号 | 证据支持要点 |
|---|---|---|---|
{map_rows}

## 方法与技术路线
这些论文共同覆盖了检索增强、显式的推理/行动回路、多智能体协作，以及批判/精炼机制。每篇论文的具体细节见上方的“证据映射”表；在引用任何数值型结论之前，请回溯到所引用的原始文献进行核实。

## 数据集与评估
在零密钥（mock）演示中，结构化抽取刻意保持保守：除非给定文本明确给出，否则数据集与指标字段会标记为“不可得”。切换到 `PAPER_AGENT_LLM_MODE=autogen` 并可选启用 PDF 下载，可获得更深入的抽取。

## 关键发现
- 基于证据的生成可减少对模型自身记忆的依赖，使论断更易追溯 [P1]。
- 显式的推理/行动或多智能体协作可将长篇研究流程拆解为可观测的阶段 [P2] [P3]。
- 长文研究受益于检索、问题拆解、提纲/报告综合与引用 [P4]。
- 反馈与精炼回路提供了修正中间或最终产出的一般机制 [P5] [P6]。

## 矛盾与局限
{limitations}

## 开放问题
- 如何在独立于写作质量的前提下，衡量检索质量与引用蕴含（entailment）？
- 多智能体拆解在何时能足够提升可靠性，从而值得额外的时延与 token 成本？
- 哪些工作流状态应被持久化，以支持重放、回滚与人工介入？
- 当论文之间结论冲突或基准不可比时，应如何评估报告层面的事实性？

## 参考文献
{refs}
"""

    # ------------------------------------------------------------------ #
    # 长文写作：按章节多次调用，篇幅随论文数增长（几十篇 → 上万字）
    # ------------------------------------------------------------------ #
    SHORT_SECTIONS = {"摘要", "Abstract", "研究问题"}

    @staticmethod
    def _one_line(text: str, limit: int = 160) -> str:
        collapsed = re.sub(r"\s+", " ", (text or "").strip())
        return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"

    def _compact_evidence(self, evidence: list[PaperEvidence]) -> str:
        return "\n".join(
            f"[{e.paper_id}] {e.title}｜方法：{self._one_line(e.method, 100)}｜算法：{self._one_line(e.algorithm, 100)}｜"
            f"架构：{self._one_line(e.architecture, 80)}｜公式：{self._one_line(e.formulas, 120)}｜"
            f"实验：{self._one_line(e.experiment_results, 120)}｜优点：{self._one_line(e.pros, 80)}｜"
            f"局限：{self._one_line(e.limitations, 80)}｜结论：{self._one_line(e.conclusion, 120)}"
            for e in evidence
        )

    def _detail_evidence(self, evidence: list[PaperEvidence]) -> str:
        return "\n\n".join(
            f"[{e.paper_id}] {e.title}\n"
            f"方法：{self._one_line(e.method, 300)}\n"
            f"算法：{self._one_line(e.algorithm, 300)}\n"
            f"公式：{self._one_line(e.formulas, 400)}\n"
            f"架构：{self._one_line(e.architecture, 300)}\n"
            f"数据集：{self._one_line(e.dataset, 200)}\n"
            f"实验设置：{self._one_line(e.experiment_setup, 300)}\n"
            f"实验结果：{self._one_line(e.experiment_results, 400)}\n"
            f"指标：{self._one_line(e.metrics, 160)}\n"
            f"优点：{self._one_line(e.pros, 200)}\n"
            f"局限：{self._one_line(e.limitations, 240)}\n"
            f"结论：{self._one_line(e.conclusion, 300)}\n"
            f"链接：{e.url}"
            for e in evidence
        )

    @staticmethod
    def _references(evidence: list[PaperEvidence]) -> str:
        lines = []
        for item in evidence:
            suffix = f" {item.url}" if item.url else ""
            lines.append(f"- [{item.paper_id}] {item.title}{suffix}")
        return "\n".join(lines)

    @staticmethod
    def _cell(text: str, limit: int = 120) -> str:
        collapsed = re.sub(r"\s+", " ", (text or "").strip()).replace("|", "/")
        return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"

    def _paper_table(self, evidence: list[PaperEvidence]) -> str:
        """逐篇结构化速览表（确定性生成，便于横向对比）。"""
        header = "| 编号 | 标题 | 方法 | 算法 | 架构 | 数据集 | 实验/指标 | 优点 | 局限 |"
        separator = "|---|---|---|---|---|---|---|---|---|"
        rows = []
        for item in evidence:
            experiment = f"{item.experiment_results} {item.metrics}".strip()
            cells = [
                item.paper_id,
                self._cell(item.title, 60),
                self._cell(item.method),
                self._cell(item.algorithm),
                self._cell(item.architecture),
                self._cell(item.dataset),
                self._cell(experiment),
                self._cell(item.pros),
                self._cell(item.limitations),
            ]
            rows.append("| " + " | ".join(cells) + " |")
        return "\n".join([header, separator, *rows, ""])

    @staticmethod
    def _strip_headings(text: str) -> str:
        # 去掉模型可能自带的一级/二级标题，避免与我们的章节标题重复（保留 ### 结构）
        lines = [line for line in (text or "").splitlines() if not re.match(r"^\s*#{1,2}\s", line)]
        return "\n".join(lines).strip()

    def _section_text(
        self,
        system_message: str,
        header: str,
        body: str,
        requirements: str,
        max_tokens: int,
    ) -> str:
        task = f"{header}\n\n{requirements}\n\n{body}"
        return self._autogen_text("writer_agent", system_message, task, max_tokens=max_tokens)

    def _autogen_long_report(
        self,
        topic: str,
        research_question: str,
        evidence: list[PaperEvidence],
        analysis: str,
        human_feedback: str,
        previous_draft: str,
        report_format: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> str:
        def progress(message: str) -> None:
            if on_progress:
                on_progress(message)

        spec = format_spec(report_format)
        sections = [str(name) for name in spec["sections"]]
        paper_count = len(evidence)
        target = max(
            settings.report_min_chars,
            min(settings.report_max_chars, paper_count * settings.report_chars_per_paper),
        )
        per_section = max(700, target // max(1, len(sections)))
        compact = self._compact_evidence(evidence)
        detail = self._detail_evidence(evidence)
        revision = ""
        if human_feedback:
            revision = (
                f"\n\n【人工修改要求】{human_feedback}\n"
                f"【上一版草稿（节选）】\n{previous_draft[:6000]}"
            )

        system_message = writer_system(report_format)
        written: dict[str, str] = {}
        writable = [name for name in sections if name not in DETERMINISTIC_SECTIONS] or ["摘要"]
        total_steps = len(writable)
        step = 0

        progress("写作智能体正在规划报告提纲…")
        outline = self._build_outline(topic, research_question, evidence, analysis, writable)

        for section in sections:
            if section == "参考文献":
                written[section] = self._references(evidence)
                continue
            if section == "论文速览":
                written[section] = self._paper_table(evidence)
                continue

            step += 1
            progress(f"写作智能体正在撰写「{section}」（{step}/{total_steps}）")
            section_target = 320 if section in self.SHORT_SECTIONS else per_section
            header = f"研究主题：{topic}\n研究问题：{research_question}\n论文总数：{paper_count}"
            requirements = (
                f"【撰写任务】只写「{section}」这一节，不要写其它章节。\n"
                f"【篇幅要求】本节不少于 {section_target} 个汉字；请充分展开、给出细节，不要泛泛而谈。\n"
                f"【引用要求】任何涉及具体论文的论断都要标注编号，如 [P1]；不得编造数据或结论。\n"
                f"【输出要求】只输出本节正文（Markdown）；不要输出一级/二级标题；不要在末尾附参考文献。"
            )
            if written:
                requirements += f"\n【已完成章节】{'、'.join(written)}（保持术语一致，不要重复其内容）。"
            hint = SECTION_HINTS.get(section)
            if hint:
                requirements += f"\n【本节要点】{hint}"
            points = outline.get(section)
            if points:
                requirements += f"\n【本节提纲】{'；'.join(points[:6])}"

            if section in PAPER_DETAIL_SECTIONS and paper_count > settings.paper_detail_batch_size:
                written[section] = self._write_paper_detail(
                    system_message, header, evidence, section, per_section, progress
                )
            elif section in PAPER_DETAIL_SECTIONS:
                body = f"【分析总览】\n{analysis}\n\n【逐篇证据】\n{detail}{revision}"
                written[section] = self._strip_headings(
                    self._section_text(system_message, header, body, requirements, settings.writer_section_max_tokens)
                )
            else:
                body = f"【分析总览】\n{analysis}\n\n【证据清单】\n{compact}{revision}"
                written[section] = self._strip_headings(
                    self._section_text(system_message, header, body, requirements, settings.writer_section_max_tokens)
                )

        full_count = sum(1 for item in evidence if getattr(item, "evidence_level", "") == "全文")
        abstract_only = [item.paper_id for item in evidence if getattr(item, "evidence_level", "") != "全文"]
        body_chunks = []
        for section in sections:
            content = (written.get(section, "") or "").strip() or "（本节暂无内容）"
            body_chunks.append(f"\n## {section}\n\n{content}\n")
        body_text = "\n".join(body_chunks)

        # 引用一致性：找出正文从未引用的论文
        cited = set(re.findall(r"\[(P\d+)\]", body_text))
        uncited = [item.paper_id for item in evidence if item.paper_id not in cited]

        coverage = f"｜证据覆盖：全文 {full_count} 篇 / 摘要 {len(evidence) - full_count} 篇"
        if abstract_only:
            coverage += f"（仅摘要：{', '.join(abstract_only)}）"
        if uncited:
            coverage += f"｜未被正文引用：{', '.join(uncited)}"

        report = "\n".join(
            [
                f"# Paper-Agent 调研报告：{topic}",
                f"\n> 版式：{format_label(report_format)}｜论文数：{paper_count}｜目标篇幅：约 {target} 字{coverage}\n",
                body_text,
            ]
        )
        progress(f"写作完成，共 {len(report)} 字")
        return report

    def _build_outline(
        self,
        topic: str,
        research_question: str,
        evidence: list[PaperEvidence],
        analysis: str,
        sections: list[str],
    ) -> dict[str, list[str]]:
        if not evidence:
            return {}
        task = (
            f"研究主题：{topic}\n研究问题：{research_question}\n"
            f"章节列表：{'、'.join(sections)}\n\n"
            f"证据清单：\n{self._compact_evidence(evidence)}\n\n"
            f"分析：\n{analysis[:4000]}\n\n请按 JSON 输出每一章的要点与应引用的论文。"
        )
        try:
            raw = self._autogen_text("outline_agent", OUTLINE_SYSTEM, task, max_tokens=2048)
            data = extract_json_object(raw)
        except Exception:  # noqa: BLE001 - 提纲失败不阻断写作
            return {}
        outline: dict[str, list[str]] = {}
        for item in data.get("sections", []) or []:
            name = str(item.get("name", "")).strip()
            points = [str(point).strip() for point in item.get("points", []) if str(point).strip()]
            if name and points:
                outline[name] = points
        return outline

    def _write_paper_detail(
        self,
        system_message: str,
        header: str,
        evidence: list[PaperEvidence],
        section: str,
        per_section: int,
        progress: Callable[[str], None],
    ) -> str:
        batch_size = max(2, settings.paper_detail_batch_size)
        batches = [evidence[i : i + batch_size] for i in range(0, len(evidence), batch_size)]
        parts: list[str] = []
        for index, batch in enumerate(batches, start=1):
            progress(f"写作智能体正在撰写「{section}」· 第 {index}/{len(batches)} 批论文")
            requirements = (
                f"【撰写任务】为下列 {len(batch)} 篇论文各写一段较详细的中文介绍，作为「{section}」的一部分。\n"
                f"【篇幅要求】每篇论文不少于 180 个汉字，本批合计不少于 {max(600, per_section // 2)} 字。\n"
                f"【内容要求】逐篇说明：研究问题、方法与算法步骤、架构/网络、数据集与实验设置、主要结果、优点与局限，以及它与其它论文的关系。公式用 LaTeX。原文未提供的信息写“未提及”，不要编造。\n"
                f"【输出要求】用无序列表，每条形如 `- **[P1] 标题**：……`；不要输出一级/二级标题，不要附参考文献。"
            )
            text = self._section_text(
                system_message,
                header,
                f"【逐篇证据】\n{self._detail_evidence(batch)}",
                requirements,
                settings.writer_section_max_tokens,
            )
            stripped = self._strip_headings(text)
            if stripped:
                parts.append(stripped)
        return "\n\n".join(parts)

    @staticmethod
    def _to_review_result(data: dict[str, Any]) -> ReviewResult:
        def as_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        def as_score(value: Any) -> float:
            match = re.search(r"\d+(?:\.\d+)?", str(value))
            if not match:
                return 3.0
            return max(0.0, min(5.0, float(match.group(0))))

        verdict = str(data.get("verdict", "revise")).strip().lower()
        if verdict not in {"pass", "revise"}:
            verdict = "revise"
        issues = as_list(data.get("issues"))
        required = as_list(data.get("required_changes")) or issues
        return ReviewResult(
            score=as_score(data.get("score", 3.0)),
            strengths=as_list(data.get("strengths")),
            issues=issues,
            required_changes=required,
            verdict=verdict,
        )

    def review_report(self, report: str, evidence: list[PaperEvidence]) -> ReviewResult:
        evidence_text = "\n".join(f"[{e.paper_id}] {e.title}: {e.conclusion}" for e in evidence)
        if self.mode == "autogen":
            try:
                raw = self._autogen_text(
                    "reviewer_agent",
                    REVIEWER_SYSTEM,
                    f"Evidence:\n{evidence_text}\n\nReport:\n{report[: settings.report_max_chars + 8000]}",
                )
                return self._to_review_result(extract_json_object(raw))
            except Exception:  # noqa: BLE001 - 解析失败给出保守评审
                return ReviewResult(
                    score=3.0,
                    strengths=[],
                    issues=["评审智能体输出格式异常，已跳过自动评审；请人工判断。"],
                    required_changes=[],
                    verdict="revise",
                )

        # 版式可配置，章节标题不再固定，改用“二级标题数量”做通用结构检查
        headings = len(re.findall(r"(?m)^##\s+\S", report))
        citation_ids = {e.paper_id for e in evidence}
        present = {pid for pid in citation_ids if f"[{pid}]" in report}
        coverage = len(present) / max(1, len(citation_ids))
        score = 3.0 + 2.0 * coverage
        issues: list[str] = []
        if headings < 5:
            issues.append(f"报告章节偏少（检测到 {headings} 个二级标题），建议补充完整结构。")
            score -= 0.4 * (5 - headings)
        if coverage < 0.8:
            issues.append(f"引用覆盖率仅 {coverage:.0%}，部分证据未被引用。")
        lowered = report.lower()
        if not any(term in lowered for term in ("verify", "limitation", "核实", "局限")):
            issues.append("报告应更明确地说明证据/核实方面的局限。")
        score = max(0.0, min(5.0, score))
        verdict = "pass" if score >= 4.0 and not issues else "revise"
        return ReviewResult(
            score=round(score, 2),
            strengths=["论文编号可追溯", "章节结构清晰", "对指标采取保守处理"],
            issues=issues,
            required_changes=issues.copy(),
            verdict=verdict,
        )
