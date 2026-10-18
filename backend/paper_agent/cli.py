from __future__ import annotations

import platform
import sys
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from .config import settings
from .graph import PaperAgentWorkflow
from .prompts import FORMAT_SPECS
from .schemas import TaskCreate
from .utils import timestamp_id


def _configure_utf8_output() -> None:
    """Avoid UnicodeEncodeError on legacy Windows consoles (e.g. GBK/cp936).

    rich renders Markdown bullets as ``\u2022``, which cannot be encoded by a
    GBK console. Reconfiguring the standard streams to UTF-8 keeps the CLI from
    crashing after a report has already been written.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_configure_utf8_output()

app = typer.Typer(add_completion=False, help="Paper-Agent literature research demo")
console = Console()


def _run_once(request: TaskCreate, interactive: bool) -> dict:
    workflow = PaperAgentWorkflow()
    task_id = timestamp_id()
    payload = request.model_dump()
    console.print(f"[bold]Task[/bold] {task_id} | source={request.source} | llm={settings.llm_mode}")
    try:
        result = workflow.run(task_id, payload)
        values, interrupt_payload = workflow.get_state(task_id)
        while interrupt_payload:
            console.print("\n[bold yellow]Human review required[/bold yellow]")
            console.print(Markdown(values.get("draft_report", "")))
            console.print(f"\nReviewer: {values.get('review', {})}")
            if not interactive:
                action, feedback = "approve", ""
            else:
                action = typer.prompt("Action [approve/revise/reject]", default="approve").strip().lower()
                feedback = ""
                if action == "revise":
                    feedback = typer.prompt("Revision feedback")
            result = workflow.resume(task_id, action, feedback)
            values, interrupt_payload = workflow.get_state(task_id)
        return values or result
    finally:
        workflow.close()


@app.command()
def doctor():
    """Print environment and configuration checks."""
    table = Table(title="Paper-Agent doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", platform.platform())
    table.add_row("LLM mode", settings.llm_mode)
    table.add_row("Paper source", settings.source)
    table.add_row("Source options", "sample/arxiv/semantic_scholar/openalex/crossref")
    table.add_row("Report formats", "/".join(FORMAT_SPECS))
    table.add_row("Max papers ceiling", str(settings.max_papers_ceiling))
    table.add_row("Top-K ceiling", str(settings.top_k_ceiling))
    table.add_row("Model", settings.openai_model)
    table.add_row("OpenAI/base URL configured", str(bool(settings.openai_api_key or settings.openai_base_url)))
    table.add_row("Workspace", str(settings.workspace))
    table.add_row("Checkpoint DB", str(settings.checkpoint_db))
    console.print(table)
    if sys.version_info < (3, 11):
        raise typer.Exit(code=1)


@app.command()
def demo():
    """Run the zero-key bundled demo and write a report."""
    request = TaskCreate(
        topic="Agentic RAG and multi-agent literature research systems",
        research_question="How do retrieval, multi-agent decomposition, and feedback loops improve research report generation?",
        max_papers=6,
        top_k=5,
        source="sample",
        require_human_review=False,
    )
    result = _run_once(request, interactive=False)
    console.print("\n[bold green]Demo completed[/bold green]")
    console.print(f"Report: {result.get('report_path', '')}")
    console.print(Markdown(result.get("final_report", result.get("draft_report", ""))))


@app.command()
def run(
    topic: str = typer.Option(..., "--topic", "-t"),
    question: str = typer.Option("", "--question", "-q"),
    source: list[str] = typer.Option(
        ["sample"],
        "--source",
        "-s",
        help="可多次指定：sample / arxiv / semantic_scholar / openalex / crossref",
    ),
    report_format: str = typer.Option(
        "general",
        "--format",
        "-f",
        help="报告版式：" + " / ".join(FORMAT_SPECS),
    ),
    max_papers: int = typer.Option(6, min=2, max=settings.max_papers_ceiling),
    top_k: int = typer.Option(5, min=2, max=settings.top_k_ceiling),
    human_review: bool = typer.Option(True, "--human-review/--no-human-review"),
):
    """Run one research task from the terminal."""
    request = TaskCreate(
        topic=topic,
        research_question=question,
        source=source[0] if source else "sample",
        sources=list(source),
        report_format=report_format,
        max_papers=max_papers,
        top_k=top_k,
        require_human_review=human_review,
    )
    result = _run_once(request, interactive=human_review)
    console.print(f"\n[bold green]Status:[/bold green] {result.get('status')}")
    if result.get("report_path"):
        console.print(f"Report: {result['report_path']}")


@app.command()
def serve(
    host: str = typer.Option(settings.host),
    port: int = typer.Option(settings.port),
    reload: bool = typer.Option(False),
):
    """Start FastAPI backend."""
    import uvicorn

    uvicorn.run("paper_agent.api:app", host=host, port=port, reload=reload)


@app.command("eval")
def eval_task(task_id: str = typer.Argument(..., help="Completed task id")):
    """Evaluate one completed report with deterministic demo metrics."""
    from .eval import evaluate_task
    metrics = evaluate_task(task_id)
    table = Table(title=f"Evaluation: {task_id}")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in metrics.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def benchmark(top_k: int = typer.Option(5, min=1, max=8)):
    """Run the tiny bundled retrieval sanity benchmark."""
    from .benchmark import run_sample_retrieval_benchmark
    result = run_sample_retrieval_benchmark(top_k)
    console.print(f"[bold]{result['metric']}[/bold] = {result['value']:.1%} on {result['cases']} tiny demo cases")
    console.print(result['note'])
    for row in result['details']:
        console.print(f"- {row['query']} -> {row['top_k']} | relevant={row['relevant']} | hit={row['hit']}")


if __name__ == "__main__":
    app()
