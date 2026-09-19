import agentic.agents.valuation_analyst as valuation_analyst
from agentic.rag.citations import CitedInsight
from tests.conftest import FakeDataProvider


class _FakeAgentResult:
    def __init__(self, output):
        self.output = output


def _patch_inputs(monkeypatch, *, excerpts, ingest_caveat=None):
    async def fake_ratios(provider, symbol):
        return {"pe_ratio": 20.0, "pb_ratio": 5.0, "roe": 0.3, "fcf_per_share": 4.0}

    async def fake_dcf(provider, symbol):
        return {"fair_value_per_share": 100.0, "wacc": 0.09, "growth_rate": 0.03}

    async def fake_peers(symbol):
        return ["PEER"]

    async def fake_ensure(symbol):
        return ingest_caveat

    async def fake_search(symbol, query):
        return excerpts

    monkeypatch.setattr(valuation_analyst, "get_valuation_ratios", fake_ratios)
    monkeypatch.setattr(valuation_analyst, "run_dcf_lite", fake_dcf)
    monkeypatch.setattr(valuation_analyst, "find_peers", fake_peers)
    monkeypatch.setattr(valuation_analyst, "ensure_filings_ingested", fake_ensure)
    monkeypatch.setattr(valuation_analyst, "search_filings_tool", fake_search)


async def test_valuation_citations_carry_source_from_retrieved_excerpt(monkeypatch):
    excerpts = [{"text": "Credit risk in the portfolio.", "metadata": {"filing_type": "10-K", "filing_date": "2025-10-31"}}]
    _patch_inputs(monkeypatch, excerpts=excerpts)

    async def fake_run(prompt):
        assert "[1] (10-K, filed 2025-10-31)" in prompt
        return _FakeAgentResult(
            valuation_analyst._FilingInsight(
                citations=[
                    CitedInsight(insight="Discloses credit risk.", excerpt_number=1),
                    CitedInsight(insight="Made-up source.", excerpt_number=9),
                ]
            )
        )

    monkeypatch.setattr(valuation_analyst._filing_insight_agent, "run", fake_run)

    report = await valuation_analyst.analyze_valuation(FakeDataProvider(), "TEST")

    assert len(report.filing_citations) == 1
    citation = report.filing_citations[0]
    assert citation.insight == "Discloses credit risk."
    assert (citation.filing_type, citation.filing_date) == ("10-K", "2025-10-31")
    assert citation.excerpt == "Credit risk in the portfolio."
    assert any("1 filing insight(s) dropped" in c for c in report.caveats)


async def test_valuation_surfaces_ingest_failure_as_caveat_and_skips_llm(monkeypatch):
    _patch_inputs(monkeypatch, excerpts=[], ingest_caveat="Could not ingest SEC filings for TEST: boom")

    async def must_not_run(prompt):
        raise AssertionError("LLM should not be called without excerpts")

    monkeypatch.setattr(valuation_analyst._filing_insight_agent, "run", must_not_run)

    report = await valuation_analyst.analyze_valuation(FakeDataProvider(), "TEST")

    assert report.filing_citations == []
    assert "Could not ingest SEC filings for TEST: boom" in report.caveats
    assert report.dcf.fair_value_per_share == 100.0
