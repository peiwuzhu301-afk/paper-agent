from paper_agent.config import settings
from paper_agent.llm import AgentSuite
from paper_agent.prompts import DETERMINISTIC_SECTIONS, FORMAT_SPECS
from paper_agent.schemas import PaperEvidence


def _evidence(count: int) -> list[PaperEvidence]:
    return [
        PaperEvidence(
            paper_id=f"P{i}",
            title=f"Paper {i}",
            method="method",
            conclusion="conclusion",
            url=f"https://example.test/{i}",
        )
        for i in range(1, count + 1)
    ]


def test_long_form_assembles_every_section(monkeypatch):
    calls: list[tuple[str, int | None]] = []

    def fake(self, name, system_message, task, max_tokens=None):  # noqa: ANN001
        calls.append((name, max_tokens))
        return "本段正文引用 [P1]，并给出细节。"

    monkeypatch.setattr(AgentSuite, "_autogen_text", fake)

    suite = AgentSuite("autogen")
    report = suite.write_report("主题X", "问题Y", _evidence(3), "分析Z", report_format="ieee")

    sections = FORMAT_SPECS["ieee"]["sections"]
    for section in sections:
        assert f"## {section}" in report
    # 论文速览与参考文献由证据确定性生成，不调用模型
    deterministic = len(set(sections) & DETERMINISTIC_SECTIONS)
    writer_calls = [call for call in calls if call[0] == "writer_agent"]
    assert len(writer_calls) == len(sections) - deterministic
    assert all(tokens == settings.writer_section_max_tokens for _, tokens in writer_calls)
    assert "| P1 |" in report
    assert "[P1] Paper 1" in report


def test_paper_detail_section_is_batched(monkeypatch):
    calls: list[str] = []

    def fake(self, name, system_message, task, max_tokens=None):  # noqa: ANN001
        calls.append(task)
        return "细节 [P1]。"

    monkeypatch.setattr(AgentSuite, "_autogen_text", fake)

    suite = AgentSuite("autogen")
    # 论文数超过批次大小，相关工作应分批生成
    count = settings.paper_detail_batch_size * 2 + 1
    suite.write_report("主题", "问题", _evidence(count), "分析", report_format="ieee")

    detached = [task for task in calls if "「相关工作」" in task]
    expected = -(-count // settings.paper_detail_batch_size)  # 向上取整
    assert len(detached) == expected
