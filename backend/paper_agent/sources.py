from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from pypdf import PdfReader
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from .config import settings
from .sample_data import SAMPLE_PAPERS
from .schemas import PaperRecord


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
USER_AGENT = "Paper-Agent-Demo/1.0 (https://github.com/paper-agent-demo)"


class SourceRateLimited(RuntimeError):
    """来源触发限流；不应重试，交给多源聚合降级处理。"""


# --------------------------------------------------------------------------- #
# 归一化与去重辅助
# --------------------------------------------------------------------------- #
def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _clean_markup(text: str) -> str:
    """去掉 JATS/HTML 标签与多余空白（Crossref 摘要常是 XML 片段）。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _inv_index_to_text(index: dict[str, list[int]] | None) -> str:
    """OpenAlex 的 abstract_inverted_index 还原为正文。"""
    if not index:
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in index.items():
        for pos in positions:
            pairs.append((int(pos), word))
    pairs.sort()
    return " ".join(word for _, word in pairs)


def _paper_key(paper: PaperRecord) -> str:
    if paper.doi:
        return f"doi:{paper.doi.lower()}"
    match = re.search(r"arxiv\.org/abs/([^/?#]+)", paper.url or "")
    if match:
        return f"arxiv:{match.group(1).lower()}"
    return f"title:{_norm_title(paper.title)}"


def _first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


# --------------------------------------------------------------------------- #
# 全文（PDF）下载与解析
# --------------------------------------------------------------------------- #
def _extract_pdf_text(content: bytes, max_chars: int) -> str:
    reader = PdfReader(io.BytesIO(content))
    chunks: list[str] = []
    total = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        if text:
            chunks.append(text)
            total += len(text)
        if total >= max_chars:
            break
    return "\n".join(chunks)[:max_chars]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
def _download_bytes(url: str, max_bytes: int) -> bytes:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
            response.raise_for_status()
            buffer = bytearray()
            for chunk in response.iter_bytes():
                buffer.extend(chunk)
                if len(buffer) >= max_bytes:
                    break
            return bytes(buffer)


def fetch_full_text(
    pdf_url: str,
    dest_path: Path | None = None,
    max_chars: int = 36000,
    max_bytes: int = 20_000_000,
) -> str:
    """下载 PDF、保存到本地（可选），并抽取正文文本。"""
    if not pdf_url:
        return ""
    content = _download_bytes(pdf_url, max_bytes)
    if dest_path is not None:
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(content)
        except OSError:
            pass
    return _extract_pdf_text(content, max_chars)


# --------------------------------------------------------------------------- #
# 各来源
# --------------------------------------------------------------------------- #
class PaperSource:
    label = "source"

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        raise NotImplementedError


class SamplePaperSource(PaperSource):
    label = "内置示例"

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        words = {
            w.lower()
            for q in queries
            for w in re.findall(r"[a-zA-Z]{3,}|[\u4e00-\u9fff]{2,}", q)
        }

        def score(item: dict) -> tuple[int, int]:
            haystack = f"{item['title']} {item['abstract']}".lower()
            overlap = sum(1 for word in words if word in haystack)
            return overlap, item.get("year") or 0

        ordered = sorted(SAMPLE_PAPERS, key=score, reverse=True)
        records = []
        for item in ordered[:max_results]:
            record = PaperRecord(**item)
            record.source = "sample"
            records.append(record)
        return records


class ArxivPaperSource(PaperSource):
    label = "arXiv"
    endpoint = "https://export.arxiv.org/api/query"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def _request(self, query: str, max_results: int) -> str:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        with httpx.Client(timeout=settings.request_timeout, follow_redirects=True) as client:
            response = client.get(self.endpoint, params=params, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return response.text

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        per_query = max(2, min(max_results, 20))
        found: dict[str, PaperRecord] = {}
        for query in queries[:3]:
            xml_text = self._request(query, per_query)
            root = ET.fromstring(xml_text)
            for entry in root.findall("atom:entry", ATOM_NS):
                raw_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
                arxiv_id = raw_id.rstrip("/").split("/")[-1]
                if not arxiv_id or arxiv_id in found:
                    continue
                title = " ".join((entry.findtext("atom:title", default="", namespaces=ATOM_NS)).split())
                abstract = " ".join((entry.findtext("atom:summary", default="", namespaces=ATOM_NS)).split())
                authors = [
                    name.text.strip()
                    for author in entry.findall("atom:author", ATOM_NS)
                    if (name := author.find("atom:name", ATOM_NS)) is not None and name.text
                ]
                published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
                year = int(published[:4]) if published[:4].isdigit() else None
                found[arxiv_id] = PaperRecord(
                    paper_id="",
                    title=title,
                    authors=authors,
                    year=year,
                    abstract=abstract,
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                    source="arxiv",
                )
                if len(found) >= max_results:
                    break
            if len(found) >= max_results:
                break
        return list(found.values())[:max_results]

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    def download_full_text(self, paper: PaperRecord) -> str:
        return fetch_full_text(
            paper.pdf_url,
            dest_path=None,
            max_chars=settings.arxiv_max_fulltext_chars,
            max_bytes=settings.pdf_max_bytes,
        )


class SemanticScholarPaperSource(PaperSource):
    label = "Semantic Scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,abstract,year,authors,url,externalIds,openAccessPdf"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_not_exception_type(SourceRateLimited),
        reraise=True,
    )
    def _request(self, query: str, limit: int) -> dict[str, Any]:
        params = {"query": query, "limit": max(1, min(limit, 100)), "fields": self.fields}
        headers = {"User-Agent": USER_AGENT}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
        with httpx.Client(timeout=settings.request_timeout, follow_redirects=True) as client:
            response = client.get(self.endpoint, params=params, headers=headers)
            if response.status_code == 429:
                raise SourceRateLimited("Semantic Scholar 触发限流（429）；可配置 SEMANTIC_SCHOLAR_API_KEY 提升额度")
            response.raise_for_status()
            return response.json()

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        found: dict[str, PaperRecord] = {}
        for query in queries[:3]:
            if len(found) >= max_results:
                break
            data = self._request(query, max_results)
            for item in data.get("data", []):
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                external = item.get("externalIds") or {}
                doi = (external.get("DOI") or "").strip().lower()
                arxiv_id = external.get("ArXiv")
                key = doi or (f"arxiv:{str(arxiv_id).lower()}" if arxiv_id else _norm_title(title))
                if key in found:
                    continue
                pdf = (item.get("openAccessPdf") or {}).get("url") or ""
                url = item.get("url") or (f"https://doi.org/{doi}" if doi else "")
                found[key] = PaperRecord(
                    paper_id="",
                    title=title,
                    authors=[a.get("name", "") for a in item.get("authors", []) if a.get("name")],
                    year=item.get("year"),
                    abstract=(item.get("abstract") or "").strip(),
                    url=url,
                    pdf_url=pdf,
                    doi=doi,
                    source="semantic_scholar",
                )
                if len(found) >= max_results:
                    break
        return list(found.values())[:max_results]


class OpenAlexPaperSource(PaperSource):
    label = "OpenAlex"
    endpoint = "https://api.openalex.org/works"
    select = (
        "id,doi,title,publication_year,authorships,primary_location,abstract_inverted_index"
    )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def _request(self, query: str, per_page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "search": query,
            "per-page": max(1, min(per_page, 100)),
            "select": self.select,
        }
        if settings.contact_email:
            params["mailto"] = settings.contact_email
        with httpx.Client(timeout=settings.request_timeout, follow_redirects=True) as client:
            response = client.get(self.endpoint, params=params, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return response.json()

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        found: dict[str, PaperRecord] = {}
        for query in queries[:3]:
            if len(found) >= max_results:
                break
            data = self._request(query, max_results)
            for item in data.get("results", []):
                title = (item.get("title") or item.get("display_name") or "").strip()
                if not title:
                    continue
                doi = (item.get("doi") or "").replace("https://doi.org/", "").strip().lower()
                key = doi or _norm_title(title)
                if key in found:
                    continue
                location = item.get("primary_location") or {}
                url = item.get("doi") or location.get("landing_page_url") or item.get("id") or ""
                found[key] = PaperRecord(
                    paper_id="",
                    title=title,
                    authors=[
                        (authorship.get("author") or {}).get("display_name", "")
                        for authorship in item.get("authorships", [])
                        if (authorship.get("author") or {}).get("display_name")
                    ],
                    year=item.get("publication_year"),
                    abstract=_inv_index_to_text(item.get("abstract_inverted_index")),
                    url=url,
                    pdf_url=location.get("pdf_url") or "",
                    doi=doi,
                    source="openalex",
                )
                if len(found) >= max_results:
                    break
        return list(found.values())[:max_results]


class CrossrefPaperSource(PaperSource):
    label = "Crossref"
    endpoint = "https://api.crossref.org/works"
    select = "DOI,title,abstract,author,issued,URL"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def _request(self, query: str, rows: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "query.bibliographic": query,
            "rows": max(1, min(rows, 100)),
            "select": self.select,
        }
        if settings.contact_email:
            params["mailto"] = settings.contact_email
        with httpx.Client(timeout=settings.request_timeout, follow_redirects=True) as client:
            response = client.get(self.endpoint, params=params, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return response.json()

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        found: dict[str, PaperRecord] = {}
        for query in queries[:3]:
            if len(found) >= max_results:
                break
            data = self._request(query, max_results)
            for item in (data.get("message") or {}).get("items", []):
                title = _first(item.get("title")).strip()
                if not title:
                    continue
                doi = (item.get("DOI") or "").strip().lower()
                key = doi or _norm_title(title)
                if key in found:
                    continue
                year = None
                date_parts = ((item.get("issued") or {}).get("date-parts") or [[]])[0]
                if date_parts and isinstance(date_parts[0], int):
                    year = date_parts[0]
                authors = [
                    f"{author.get('given', '')} {author.get('family', '')}".strip()
                    for author in item.get("author", [])
                    if author.get("family") or author.get("given")
                ]
                found[key] = PaperRecord(
                    paper_id="",
                    title=title,
                    authors=authors,
                    year=year,
                    abstract=_clean_markup(item.get("abstract") or ""),
                    url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                    doi=doi,
                    source="crossref",
                )
                if len(found) >= max_results:
                    break
        return list(found.values())[:max_results]


# --------------------------------------------------------------------------- #
# 多源聚合：总量平均分配 + 去重 + 失败降级
# --------------------------------------------------------------------------- #
class MultiPaperSource(PaperSource):
    label = "多源聚合"

    def __init__(self, sources: list[PaperSource]) -> None:
        self.sources = sources
        self.errors: list[str] = []

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        self.errors = []
        if not self.sources:
            return SamplePaperSource().search(queries, max_results)

        total = max(1, int(max_results))
        count = len(self.sources)
        base, extra = divmod(total, count)
        quotas = [base + (1 if idx < extra else 0) for idx in range(count)]

        merged: list[PaperRecord] = []
        seen: set[str] = set()
        satisfied: list[PaperSource] = []

        for source, quota in zip(self.sources, quotas):
            wanted = max(quota, 1)
            try:
                items = source.search(queries, wanted)
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响整体
                self.errors.append(f"{source.label}: {exc}")
                continue
            added = 0
            for item in items:
                key = _paper_key(item)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                added += 1
            if added >= wanted:
                satisfied.append(source)

        # 若总量不足（有的源配额未取满），从配额已取满的来源再补一些
        for source in satisfied:
            if len(merged) >= total:
                break
            try:
                items = source.search(queries, total)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{source.label}: {exc}")
                continue
            for item in items:
                if len(merged) >= total:
                    break
                key = _paper_key(item)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)

        for index, paper in enumerate(merged, start=1):
            paper.paper_id = f"P{index}"
        return merged[:total]


SOURCE_REGISTRY: dict[str, type[PaperSource]] = {
    "sample": SamplePaperSource,
    "arxiv": ArxivPaperSource,
    "semantic_scholar": SemanticScholarPaperSource,
    "openalex": OpenAlexPaperSource,
    "crossref": CrossrefPaperSource,
}


def build_source(name: str) -> PaperSource:
    """构建单一来源（向后兼容）。"""
    return SOURCE_REGISTRY.get((name or "").strip().lower(), SamplePaperSource)()


def build_sources(names: list[str] | None) -> MultiPaperSource:
    """构建多源聚合器。未知来源会被忽略；为空时回退到内置示例。"""
    resolved: list[PaperSource] = []
    for name in names or []:
        key = (name or "").strip().lower()
        factory = SOURCE_REGISTRY.get(key)
        if factory and all(not isinstance(existing, factory) for existing in resolved):
            resolved.append(factory())
    if not resolved:
        resolved.append(SamplePaperSource())
    return MultiPaperSource(resolved)
