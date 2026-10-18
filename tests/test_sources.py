from paper_agent.schemas import PaperRecord
from paper_agent.sources import MultiPaperSource, PaperSource, _paper_key


class FakeSource(PaperSource):
    def __init__(self, label: str, records: list[PaperRecord]) -> None:
        self.label = label
        self._records = records

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        return [record.model_copy(deep=True) for record in self._records[:max_results]]


class BoomSource(PaperSource):
    label = "boom"

    def search(self, queries: list[str], max_results: int) -> list[PaperRecord]:
        raise RuntimeError("network down")


def _paper(title: str, doi: str = "", url: str = "") -> PaperRecord:
    return PaperRecord(paper_id="", title=title, doi=doi, url=url, source="fake")


def test_multi_source_splits_evenly_and_dedupes():
    source_a = FakeSource("A", [_paper("Shared Paper", doi="10.1/x"), _paper("Alpha Only")])
    source_b = FakeSource("B", [_paper("Shared Paper", doi="10.1/x"), _paper("Beta Only")])
    aggregator = MultiPaperSource([source_a, source_b])

    result = aggregator.search(["query"], 2)

    assert len(result) == 2
    assert [paper.paper_id for paper in result] == ["P1", "P2"]
    titles = [paper.title for paper in result]
    assert titles.count("Shared Paper") == 1
    assert aggregator.errors == []


def test_multi_source_degrades_when_one_source_fails():
    aggregator = MultiPaperSource([BoomSource(), FakeSource("OK", [_paper("Only Paper")])])

    result = aggregator.search(["query"], 3)

    assert [paper.title for paper in result] == ["Only Paper"]
    assert aggregator.errors and "boom" in aggregator.errors[0]


def test_paper_key_prefers_doi_then_arxiv_then_title():
    assert _paper_key(_paper("Title", doi="10.1/ABC")) == "doi:10.1/abc"
    assert _paper_key(_paper("Title", url="https://arxiv.org/abs/2401.12345v1")) == "arxiv:2401.12345v1"
    assert _paper_key(_paper("A Title!")) == _paper_key(_paper("a title"))
