from paper_agent.eval import evaluate_snapshot


def test_eval_metrics():
    report = "\n".join([f"## {s}" for s in [
        "Executive Summary", "Research Question", "Evidence Map", "Methods and Approaches",
        "Dataset and Evaluation", "Key Findings", "Contradictions and Limitations", "Open Questions", "References"
    ]]) + "\n[P1] [P2]"
    metrics = evaluate_snapshot({
        "papers": [{"paper_id": "P1"}, {"paper_id": "P2"}],
        "evidence": [{"paper_id": "P1"}, {"paper_id": "P2"}],
        "final_report": report,
        "review": {"score": 4.5, "verdict": "pass"},
    })
    assert metrics["structured_parse_rate"] == 1.0
    assert metrics["citation_coverage"] == 1.0
    assert metrics["section_coverage"] == 1.0
