"""Single-LLM-call tier.

Ratios/DCF/peers are pure math/passthrough, computed in Python. The one
place a genuine LLM call remains is interpreting SEC filing excerpts (real
unstructured legal/business text) in the context of those already-computed
numbers — RAG retrieval (embedding similarity, `rag/retriever.py`) already
narrows to the most relevant chunks; the LLM's job is explaining what they
mean for the valuation, not re-picking them. Single, tool-free completion
(`_filing_insight_agent` has no `@agent.tool`s at all), not an agentic
tool-loop.

Minimal/simple on purpose — the content redesign (what actually belongs on
this page) is deliberately deferred; this file exists to be correct and
working against the current schema, not to be the final word on scope.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agentic.data.base import DataProvider
from agentic.llm import get_model
from agentic.rag.citations import CitedInsight, format_excerpts, resolve_citations
from agentic.schemas.valuation import DCFResult, ValuationReport
from agentic.tools.financial_metrics import get_valuation_ratios
from agentic.tools.peer_discovery import find_peers
from agentic.tools.rag_tools import ensure_filings_ingested, search_filings_tool
from agentic.tools.valuation import run_dcf_lite

_FILING_QUERY = "key business risks and financial risk factors"
_RATIO_FIELDS = ("pe_ratio", "pb_ratio", "roe", "fcf_per_share")


class _FilingInsight(BaseModel):
    citations: list[CitedInsight] = Field(
        default_factory=list,
        description=(
            "1-3 insights, each grounded in a specific, concrete detail "
            "from ONE of the numbered filing excerpts (not a generic "
            "placeholder), with that excerpt's number; empty if none of "
            "the excerpts have real analytical content."
        ),
    )


_filing_insight_agent = Agent(
    get_model("valuation"),
    output_type=_FilingInsight,
    retries={"output": 3},
    system_prompt=(
        "You are a fundamental equity analyst writing for an investor. You "
        "are given real SEC filing excerpts and already-computed valuation "
        "numbers for a company. Write 1-3 sentences, each stating a SPECIFIC "
        "fact from the excerpts (name the actual risk, business detail, or "
        "figure mentioned — e.g. 'The filing discloses credit risk exposure "
        "from its investment portfolio, relevant given the company's "
        "{fcf_per_share} FCF/share') and, where relevant, connecting it to "
        "the valuation numbers you were given. NEVER write a generic "
        "placeholder like 'Note 1' or 'Short note about risk' — every "
        "sentence must reference something concrete that actually appears "
        "in the excerpts below. The excerpts are numbered [1], [2], ...; "
        "for each insight, give the number of the ONE excerpt it comes from "
        "(a reader will be shown that excerpt next to your sentence to "
        "verify it). If an excerpt is just a table of contents "
        "or has no real analytical content, ignore it and use the others. "
        "If none of the excerpts have real content, return an empty list. "
        "Respond ONLY with the required structured output."
    ),
)


async def analyze_valuation(provider: DataProvider, symbol: str) -> ValuationReport:
    ratios = await get_valuation_ratios(provider, symbol)
    dcf = await run_dcf_lite(provider, symbol)
    peers = await find_peers(symbol)
    ingest_caveat = await ensure_filings_ingested(symbol)
    excerpts = await search_filings_tool(symbol, _FILING_QUERY)

    citations = []
    dropped = 0
    if excerpts:
        prompt = (
            f"Symbol: {symbol}\n"
            f"P/E: {ratios.get('pe_ratio')}, P/B: {ratios.get('pb_ratio')}, "
            f"ROE: {ratios.get('roe')}, FCF/share: {ratios.get('fcf_per_share')}\n"
            f"DCF fair value/share: {dcf.get('fair_value_per_share')}\n\n"
            "Filing excerpts:\n" + format_excerpts(excerpts)
        )
        result = await _filing_insight_agent.run(prompt)
        citations, dropped = resolve_citations(result.output.citations, excerpts)

    missing = [field for field in _RATIO_FIELDS if ratios.get(field) is None]
    caveats = []
    if missing:
        caveats.append(f"Missing fields: {', '.join(missing)}")
    if ingest_caveat:
        caveats.append(ingest_caveat)
    elif not excerpts:
        caveats.append("No filing excerpts found for this symbol")
    if dropped:
        caveats.append(f"{dropped} filing insight(s) dropped: they cited an excerpt number that doesn't exist")

    confidence = 1.0 - 0.1 * len(missing) - (0.05 if not excerpts else 0.0)
    confidence = max(0.0, round(confidence, 2))

    summary = (
        f"{symbol}: P/E {ratios.get('pe_ratio')} (TTM), P/B {ratios.get('pb_ratio')} (TTM), "
        f"ROE {ratios.get('roe')}. DCF fair value/share: "
        f"{dcf.get('fair_value_per_share')} (simplified, fixed assumptions). "
        f"Peers: {', '.join(peers) if peers else 'none found'}."
    )

    return ValuationReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        pe_ratio=ratios.get("pe_ratio"),
        pb_ratio=ratios.get("pb_ratio"),
        roe=ratios.get("roe"),
        fcf_per_share=ratios.get("fcf_per_share"),
        dcf=DCFResult(**dcf),
        peers=peers,
        filing_citations=citations,
        summary=summary,
    )
