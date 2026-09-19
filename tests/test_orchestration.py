from agentic.orchestration import _cross_signal_view


def _citation(insight: str) -> dict:
    return {"insight": insight, "filing_type": "10-K", "filing_date": "2025-10-31", "excerpt": "x" * 600}


def test_cross_signal_view_strips_excerpts_from_valuation():
    result = {"summary": "s", "filing_citations": [_citation("a"), _citation("b")]}
    view = _cross_signal_view("valuation", result)
    assert view["filing_citations"] == ["a", "b"]
    assert view["summary"] == "s"


def test_cross_signal_view_strips_excerpts_from_disruption():
    view = _cross_signal_view("disruption", {"filing_insights": [_citation("c")], "threats": ["t"]})
    assert view["filing_insights"] == ["c"]
    assert view["threats"] == ["t"]


def test_cross_signal_view_tolerates_old_string_citations_and_missing_field():
    assert _cross_signal_view("valuation", {"filing_citations": ["old string"]})["filing_citations"] == ["old string"]
    assert _cross_signal_view("disruption", {})["filing_insights"] == []
