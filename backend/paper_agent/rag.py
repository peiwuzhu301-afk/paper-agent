from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import chromadb

from .config import settings
from .schemas import PaperEvidence
from .utils import hash_embedding


def tokenize(text: str) -> list[str]:
    """英文按词、中文按字与二元组切分，兼顾中英文检索。"""
    text = text or ""
    words = re.findall(r"[a-z0-9]+", text.lower())
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(cjk[i : i + 2]) for i in range(len(cjk) - 1)]
    return words + cjk + bigrams


def bm25_scores(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 打分（无需任何模型，纯标准库）。"""
    if not documents:
        return []
    tokenized = [tokenize(doc) for doc in documents]
    total = len(documents)
    avgdl = (sum(len(tokens) for tokens in tokenized) / total) or 1.0
    df: Counter[str] = Counter()
    for tokens in tokenized:
        df.update(set(tokens))
    query_terms = tokenize(query)
    scores: list[float] = []
    for tokens in tokenized:
        tf = Counter(tokens)
        dl = len(tokens) or 1
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
        scores.append(score)
    return scores


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """调用外部 OpenAI 兼容 embeddings 端点（未配置则抛错，由调用方回退）。"""
    import httpx

    base = settings.embedding_base_url.rstrip("/")
    url = f"{base}/embeddings" if base.endswith("/v1") else f"{base}/v1/embeddings"
    headers = {"Content-Type": "application/json"}
    if settings.embedding_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_api_key}"
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.post(url, json={"model": settings.embedding_model, "input": texts}, headers=headers)
        response.raise_for_status()
        data = response.json().get("data", [])
    return [item["embedding"] for item in sorted(data, key=lambda row: row.get("index", 0))]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class EvidenceStore:
    """证据存储 + 检索。

    检索优先级：配置了外部 embedding 服务则用语义向量余弦相似度；
    否则回退到 BM25（比此前的哈希向量检索更可靠，且不依赖模型）。
    """

    def __init__(self, collection_name: str = "paper_agent_evidence") -> None:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Structured paper evidence for Paper-Agent"},
            embedding_function=None,
        )

    @staticmethod
    def evidence_text(item: PaperEvidence) -> str:
        return (
            f"Title: {item.title}\n"
            f"Research question: {item.research_question}\n"
            f"Method: {item.method}\n"
            f"Algorithm: {item.algorithm}\n"
            f"Formulas: {item.formulas}\n"
            f"Architecture: {item.architecture}\n"
            f"Dataset: {item.dataset}\n"
            f"Experiment setup: {item.experiment_setup}\n"
            f"Experiment results: {item.experiment_results}\n"
            f"Metrics: {item.metrics}\n"
            f"Pros: {item.pros}\n"
            f"Conclusion: {item.conclusion}\n"
            f"Limitations: {item.limitations}\n"
            f"Evidence: {item.evidence_quote}"
        )

    def upsert(self, task_id: str, evidence: list[PaperEvidence]) -> None:
        if not evidence:
            return
        ids: list[str] = []
        docs: list[str] = []
        metadatas: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        for item in evidence:
            doc_id = f"{task_id}:{item.paper_id}"
            text = self.evidence_text(item)
            ids.append(doc_id)
            docs.append(text)
            metadatas.append(
                {
                    "task_id": task_id,
                    "paper_id": item.paper_id,
                    "title": item.title,
                    "url": item.url,
                    "evidence_level": item.evidence_level,
                }
            )
            embeddings.append(hash_embedding(text))
        self.collection.upsert(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings)

    def _rank(self, query: str, documents: list[str]) -> list[float]:
        if settings.embedding_base_url and settings.embedding_model:
            try:
                vectors = _embed_texts([query] + documents)
                if len(vectors) == len(documents) + 1:
                    base = vectors[0]
                    return [_cosine(base, vector) for vector in vectors[1:]]
            except Exception:  # noqa: BLE001 - 回退 BM25
                pass
        return bm25_scores(query, documents)

    def query(self, task_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        data = self.collection.get(where={"task_id": task_id}, include=["documents", "metadatas"])
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        if not documents:
            return []
        scores = self._rank(query, documents)
        order = sorted(range(len(documents)), key=lambda idx: scores[idx], reverse=True)[:top_k]
        items: list[dict[str, Any]] = []
        for idx in order:
            metadata = metadatas[idx] or {}
            items.append(
                {
                    "document": documents[idx],
                    "paper_id": metadata.get("paper_id", ""),
                    "title": metadata.get("title", ""),
                    "url": metadata.get("url", ""),
                    "evidence_level": metadata.get("evidence_level", ""),
                    "score": round(float(scores[idx]), 4),
                }
            )
        return items

    def delete_task(self, task_id: str) -> None:
        self.collection.delete(where={"task_id": task_id})
