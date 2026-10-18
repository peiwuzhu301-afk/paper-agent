from paper_agent.utils import extract_json_object, hash_embedding, slugify, timestamp_id


def test_timestamp_id_format():
    import re

    value = timestamp_id()
    assert re.fullmatch(r"\d{8}-\d{6}", value)


def test_extract_json_handles_fences_and_prose():
    assert extract_json_object('```json\n{"queries": ["a", "b"]}\n```') == {"queries": ["a", "b"]}
    assert extract_json_object('Sure! {"queries": ["x"]} done') == {"queries": ["x"]}


def test_extract_json_repairs_common_issues():
    assert extract_json_object('{"queries": ["a", "b",],}') == {"queries": ["a", "b"]}
    assert extract_json_object("{queries: ['a', 'b']}") == {"queries": ["a", "b"]}


def test_extract_json_raises_on_garbage():
    import pytest

    with pytest.raises(Exception):
        extract_json_object("这完全不是 JSON")


def test_review_result_is_sanitized():
    from paper_agent.llm import AgentSuite

    result = AgentSuite._to_review_result(
        {"score": "4/5", "strengths": "结构清晰", "issues": ["引用不足"], "verdict": "PASS"}
    )
    assert result.score == 4.0
    assert result.verdict == "pass"
    assert result.strengths == ["结构清晰"]
    assert result.issues == ["引用不足"]



def test_hash_embedding_is_deterministic_and_normalized():
    a = hash_embedding("agentic retrieval paper research")
    b = hash_embedding("agentic retrieval paper research")
    assert a == b
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-8


def test_slugify():
    assert slugify("Paper Agent: RAG / Multi-Agent") == "paper-agent-rag-multi-agent"
