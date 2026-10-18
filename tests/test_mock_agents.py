from paper_agent.llm import AgentSuite
from paper_agent.schemas import PaperRecord


def test_mock_reader_and_writer():
    suite = AgentSuite(mode="mock")
    paper = PaperRecord(
        paper_id="P1",
        title="Example",
        abstract="A retrieval agent uses feedback and evaluation to improve generation.",
        url="https://example.test/paper",
    )
    evidence = suite.extract_evidence(paper, "How does retrieval help?")
    assert evidence.paper_id == "P1"
    report = suite.write_report(
        "retrieval agents",
        "How does retrieval help?",
        [evidence],
        "Evidence [P1] supports explicit retrieval.",
    )
    assert "## 参考文献" in report
    assert "[P1]" in report
