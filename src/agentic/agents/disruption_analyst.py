"""Single-LLM-call tier, same pattern as valuation_analyst.py.

R&D intensity, revenue growth, gross margin, and the resulting
disruption_score/posture are a deterministic weighted formula vs. a sector
benchmark (`tools/disruption.py`), not an LLM guess. The one genuine LLM
call left reads the actual fetched headlines — current information (a
pending lawsuit, a competitor's move) that a backward-looking formula
structurally cannot know about — to write grounded `opportunities`/`threats`.
Single, tool-free completion (`_disruption_insight_agent` has no
`@agent.tool`s); the prompt must explicitly forbid generic placeholder
output and demand grounding in specific headline content.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agentic.data.base import DataProvider
from agentic.llm import get_model
from agentic.rag.citations import CitedInsight, format_excerpts, resolve_citations
from agentic.schemas.disruption import DisruptionReport
from agentic.tools.disruption import get_innovation_intensity
from agentic.tools.rag_tools import ensure_filings_ingested, search_filings_tool

_NEWS_LIMIT = 10
_HEADLINE_LIMIT = 8
_FILING_QUERY = "competition, competitors, technological change, and risks of products becoming obsolete or disrupted"


class _ThreatOpportunity(BaseModel):
    opportunities: list[str] = Field(
        default_factory=list,
        description=(
            "1-3 sentences, each grounded in a specific headline or the "
            "computed metrics (not a generic statement like 'strong "
            "innovation pipeline'); empty if nothing concrete supports one."
        ),
    )
    threats: list[str] = Field(
        default_factory=list,
        description=(
            "1-3 sentences, each grounded in a specific headline or the "
            "computed metrics; empty if nothing concrete supports one."
        ),
    )
    filing_insights: list[CitedInsight] = Field(
        default_factory=list,
        description=(
            "0-3 insights about competition or technology risk, each "
            "grounded in ONE numbered 10-K excerpt (with its number); empty "
            "if no excerpts were given or none have real content."
        ),
    )


_disruption_insight_agent = Agent(
    get_model("disruption"),
    output_type=_ThreatOpportunity,
    retries={"output": 3},
    system_prompt=(
        "You are a market disruption analyst writing for an investor. You "
        "are given recent news headlines and already-computed metrics "
        "(R&D-to-revenue %, revenue growth %, a disruption score vs. sector "
        "benchmark) for a company. Write specific opportunities and threats: "
        "each sentence must reference something concrete — name the actual "
        "headline topic (a product, a lawsuit, a competitor, a market shift) "
        "or a specific number from the metrics. NEVER write a generic "
        "placeholder like 'Strong innovation pipeline' or 'Competitive "
        "pressure exists' — every sentence must be traceable to a headline "
        "or a number you were actually given. If the headlines don't "
        "support a real opportunity or threat, leave that list empty rather "
        "than inventing one. You may also be given numbered excerpts [1], "
        "[2], ... from the company's own 10-K: use them only for "
        "`filing_insights` (not for opportunities/threats), one excerpt "
        "number per insight — a reader will be shown that excerpt next to "
        "your sentence to verify it. Respond ONLY with the required "
        "structured output."
    ),
)


async def analyze_disruption(provider: DataProvider, symbol: str) -> DisruptionReport:
    metrics = await get_innovation_intensity(symbol)
    news = await provider.get_news(symbol, limit=_NEWS_LIMIT)
    headlines = [item["title"] for item in news if item.get("title")][:_HEADLINE_LIMIT]

    # Financials/profile are always FMP direct (tools/disruption.py); news
    # comes through the provider fallback chain, so its actual source can
    # vary run to run — combine both rather than hardcoding "fmp".
    sources = {"fmp"}
    if news:
        news_provider = news[0].get("_provider")
        if news_provider:
            sources.add(news_provider)
    data_source = ", ".join(sorted(sources))

    ingest_caveat = await ensure_filings_ingested(symbol)
    excerpts = await search_filings_tool(symbol, _FILING_QUERY)

    opportunities: list[str] = []
    threats: list[str] = []
    filing_insights = []
    dropped = 0
    if headlines or excerpts:
        prompt = (
            f"Symbol: {symbol}\n"
            f"R&D/revenue: {metrics.get('rd_to_revenue_pct')}%, "
            f"revenue growth: {metrics.get('revenue_growth_pct')}%, "
            f"gross margin: {metrics.get('gross_margin_pct')}%\n"
            f"Disruption score (0-100 vs. sector benchmark): "
            f"{metrics.get('disruption_score_100')} ({metrics.get('disruption_posture')})\n\n"
            "Recent headlines:\n" + ("\n".join(f"- {h}" for h in headlines) or "(none)")
        )
        if excerpts:
            prompt += "\n\n10-K excerpts:\n" + format_excerpts(excerpts)
        result = await _disruption_insight_agent.run(prompt)
        opportunities = result.output.opportunities
        threats = result.output.threats
        filing_insights, dropped = resolve_citations(result.output.filing_insights, excerpts)

    caveats = []
    if ingest_caveat:
        caveats.append(ingest_caveat)
    if dropped:
        caveats.append(f"{dropped} filing insight(s) dropped: they cited an excerpt number that doesn't exist")
    if metrics.get("rd_to_revenue_pct") is None or metrics.get("revenue_growth_pct") is None:
        caveats.append("Incomplete financial data for disruption scoring")
    if not metrics.get("sector"):
        caveats.append("Sector unavailable — used default benchmark")
    if not headlines:
        caveats.append("No recent headlines available for opportunities/threats")

    confidence = 1.0
    if metrics.get("rd_to_revenue_pct") is None:
        confidence -= 0.2
    if metrics.get("revenue_growth_pct") is None:
        confidence -= 0.2
    if not headlines:
        confidence -= 0.15
    confidence = max(0.0, round(confidence, 2))

    summary = (
        f"{symbol}: {metrics.get('disruption_posture')} posture (score "
        f"{metrics.get('disruption_score_100')}/100 vs. sector benchmark). "
        f"R&D/revenue {metrics.get('rd_to_revenue_pct')}%, revenue growth "
        f"{metrics.get('revenue_growth_pct')}%, gross margin "
        f"{metrics.get('gross_margin_pct')}%."
    )

    return DisruptionReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        data_source=data_source,
        rd_to_revenue_pct=metrics.get("rd_to_revenue_pct"),
        revenue_growth_pct=metrics.get("revenue_growth_pct"),
        disruption_posture=metrics.get("disruption_posture", "neutral"),
        disruption_risk_score=metrics.get("disruption_risk_score", 0.5),
        opportunities=opportunities,
        threats=threats,
        filing_insights=filing_insights,
        summary=summary,
    )
