import asyncio

from agentic.rag.citations import CitedInsight, format_excerpts, resolve_citations
from agentic.tools import rag_tools

_EXCERPTS = [
    {"text": "We face intense competition.", "metadata": {"filing_type": "10-K", "filing_date": "2025-10-31"}},
    {"text": "Supply chain concentration risk.", "metadata": {"filing_type": "10-K", "filing_date": "2025-10-31"}},
]


def test_format_excerpts_numbers_from_one_with_filing_header():
    text = format_excerpts(_EXCERPTS)
    assert text.startswith("[1] (10-K, filed 2025-10-31)\nWe face intense competition.")
    assert "[2] (10-K, filed 2025-10-31)\nSupply chain concentration risk." in text


def test_resolve_citations_copies_provenance_from_excerpt_not_llm():
    citations, dropped = resolve_citations([CitedInsight(insight="Competition is intense.", excerpt_number=1)], _EXCERPTS)
    assert dropped == 0
    assert citations[0].insight == "Competition is intense."
    assert citations[0].filing_type == "10-K"
    assert citations[0].filing_date == "2025-10-31"
    assert citations[0].excerpt == "We face intense competition."


def test_resolve_citations_drops_nonexistent_excerpt_numbers():
    cited = [
        CitedInsight(insight="ok", excerpt_number=2),
        CitedInsight(insight="hallucinated source", excerpt_number=7),
        CitedInsight(insight="zero is not a valid number", excerpt_number=0),
    ]
    citations, dropped = resolve_citations(cited, _EXCERPTS)
    assert [c.insight for c in citations] == ["ok"]
    assert dropped == 2


async def test_ensure_filings_ingested_skips_when_already_ingested(monkeypatch):
    calls = []
    monkeypatch.setattr(rag_tools.store, "has_filings", lambda symbol: True)
    monkeypatch.setattr(rag_tools, "ingest_filing", lambda symbol: calls.append(symbol) or 5)
    rag_tools._ingest_locks.clear()

    assert await rag_tools.ensure_filings_ingested("AAA") is None
    assert calls == []


async def test_ensure_filings_ingested_returns_caveat_instead_of_raising(monkeypatch):
    def boom(symbol):
        raise RuntimeError("SEC_EDGAR_CONTACT_EMAIL is not set")

    monkeypatch.setattr(rag_tools.store, "has_filings", lambda symbol: False)
    monkeypatch.setattr(rag_tools, "ingest_filing", boom)
    rag_tools._ingest_locks.clear()

    caveat = await rag_tools.ensure_filings_ingested("BBB")
    assert "Could not ingest SEC filings for BBB" in caveat
    assert "SEC_EDGAR_CONTACT_EMAIL" in caveat


async def test_ensure_filings_ingested_concurrent_callers_ingest_once(monkeypatch):
    ingested: set[str] = set()
    calls = []

    def has_filings(symbol):
        return symbol in ingested

    def ingest(symbol):
        calls.append(symbol)
        ingested.add(symbol)
        return 10

    monkeypatch.setattr(rag_tools.store, "has_filings", has_filings)
    monkeypatch.setattr(rag_tools, "ingest_filing", ingest)
    rag_tools._ingest_locks.clear()

    results = await asyncio.gather(*(rag_tools.ensure_filings_ingested("CCC") for _ in range(3)))
    assert results == [None, None, None]
    assert calls == ["CCC"]
