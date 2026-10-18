from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _resolve_project_root() -> Path:
    """Locate the project root across editable, source, and installed layouts.

    Editable/source installs keep ``backend/paper_agent/config.py`` inside the
    repository, so searching upwards for ``pyproject.toml`` finds the real root.
    Non-editable installs (e.g. Docker's ``pip install .``) place the package in
    site-packages, so we honor an explicit ``PAPER_AGENT_ROOT`` override and only
    fall back to the legacy ``parents[2]`` heuristic.
    """
    override = os.getenv("PAPER_AGENT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[2]


PROJECT_ROOT = _resolve_project_root()
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    workspace: Path = PROJECT_ROOT / os.getenv("PAPER_AGENT_WORKSPACE", "workspace")
    llm_mode: str = os.getenv("PAPER_AGENT_LLM_MODE", "mock").lower()
    source: str = os.getenv("PAPER_AGENT_SOURCE", "sample").lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    model_supports_vision: bool = _bool("MODEL_SUPPORTS_VISION", False)
    model_supports_function_calling: bool = _bool("MODEL_SUPPORTS_FUNCTION_CALLING", True)
    model_supports_json: bool = _bool("MODEL_SUPPORTS_JSON", True)
    model_supports_structured_output: bool = _bool("MODEL_SUPPORTS_STRUCTURED_OUTPUT", True)
    default_max_papers: int = int(os.getenv("DEFAULT_MAX_PAPERS", "6"))
    default_top_k: int = int(os.getenv("DEFAULT_TOP_K", "5"))
    max_papers_ceiling: int = int(os.getenv("MAX_PAPERS_CEILING", "40"))
    top_k_ceiling: int = int(os.getenv("TOP_K_CEILING", "15"))
    default_report_format: str = os.getenv("DEFAULT_REPORT_FORMAT", "general").lower()
    # 长文写作：按章节多次调用，篇幅随论文数增长
    long_form_writing: bool = _bool("LONG_FORM_WRITING", True)
    report_min_chars: int = int(os.getenv("REPORT_MIN_CHARS", "4000"))
    report_chars_per_paper: int = int(os.getenv("REPORT_CHARS_PER_PAPER", "600"))
    report_max_chars: int = int(os.getenv("REPORT_MAX_CHARS", "30000"))
    writer_section_max_tokens: int = int(os.getenv("WRITER_SECTION_MAX_TOKENS", "6144"))
    paper_detail_batch_size: int = int(os.getenv("PAPER_DETAIL_BATCH_SIZE", "8"))
    # 全文（PDF）下载：用于抽取算法/公式/架构/实验等只在全文出现的信息
    download_pdfs: bool = _bool("DOWNLOAD_PDFS", True)
    reader_max_chars: int = int(os.getenv("READER_MAX_CHARS", "36000"))
    pdf_max_bytes: int = int(os.getenv("PDF_MAX_BYTES", "20000000"))
    # 并发度：精读/下载/写作的并行 worker 数
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "4"))
    # LLM 调用遇到瞬时网络错误时的重试次数
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
    # 可选：外部 embedding 服务（OpenAI 兼容）。为空时回退到 BM25 检索。
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    default_human_review: bool = _bool("DEFAULT_HUMAN_REVIEW", True)
    contact_email: str = os.getenv("PAPER_AGENT_CONTACT_EMAIL", "")
    semantic_scholar_api_key: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    request_timeout: int = int(os.getenv("PAPER_AGENT_HTTP_TIMEOUT", "30"))
    arxiv_download_pdfs: bool = _bool("ARXIV_DOWNLOAD_PDFS", False)
    arxiv_max_fulltext_chars: int = int(os.getenv("ARXIV_MAX_FULLTEXT_CHARS", "24000"))
    host: str = os.getenv("PAPER_AGENT_HOST", "127.0.0.1")
    port: int = int(os.getenv("PAPER_AGENT_PORT", "8000"))
    # 单一访问口令：非空时，所有 /api 请求都需要该口令（Cookie 或 X-Access-Token 或 ?token=）
    access_token: str = os.getenv("PAPER_AGENT_ACCESS_TOKEN", "")
    # 是否由后端托管前端构建产物（frontend/dist）
    serve_frontend: bool = _bool("PAPER_AGENT_SERVE_FRONTEND", True)

    @property
    def chroma_dir(self) -> Path:
        return self.workspace / "chroma"

    @property
    def checkpoint_db(self) -> Path:
        return self.workspace / "checkpoints" / "langgraph.sqlite"

    @property
    def reports_dir(self) -> Path:
        return self.workspace / "reports"

    @property
    def runs_dir(self) -> Path:
        return self.workspace / "runs"

    @property
    def papers_dir(self) -> Path:
        return self.workspace / "papers"

    @property
    def frontend_dist(self) -> Path:
        return self.project_root / "frontend" / "dist"

    def task_papers_dir(self, task_id: str) -> Path:
        """每个任务一个独立文件夹，用于存放该任务下载的论文。"""
        return self.papers_dir / task_id

    def ensure_dirs(self) -> None:
        for path in [
            self.workspace,
            self.chroma_dir,
            self.checkpoint_db.parent,
            self.reports_dir,
            self.runs_dir,
            self.papers_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
