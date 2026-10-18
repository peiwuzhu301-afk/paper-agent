from paper_agent.llm import AgentSuite
from paper_agent.schemas import PaperRecord


def _bad_json(self, *args, **kwargs):  # noqa: ANN001
    return "这完全不是 JSON，模型跑偏了"


def test_search_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setattr(AgentSuite, "_autogen_text", _bad_json)
    suite = AgentSuite("autogen")
    queries = suite.expand_queries("大语言模型的幻觉检测", "哪些证据支持检索增强？")
    assert len(queries) == 3
    assert all(isinstance(q, str) and q.strip() for q in queries)


def test_reader_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setattr(AgentSuite, "_autogen_text", _bad_json)
    suite = AgentSuite("autogen")
    paper = PaperRecord(paper_id="P1", title="Paper", abstract="some abstract", url="u")
    evidence = suite.extract_evidence(paper, "question")
    assert evidence.paper_id == "P1"
    assert evidence.title == "Paper"


def test_reviewer_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setattr(AgentSuite, "_autogen_text", _bad_json)
    suite = AgentSuite("autogen")
    result = suite.review_report("## 摘要\n内容", [])
    assert result.verdict in {"pass", "revise"}
    assert 0 <= result.score <= 5
