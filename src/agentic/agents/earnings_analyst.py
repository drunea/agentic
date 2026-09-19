"""Plain Python, no LLM.

Surprise %, beat streak, and trend are pure arithmetic on numbers already
fetched — no qualitative text to interpret here. Earnings-call transcript
analysis (tone, evasive statements) is handled separately by
`earnings_call_analyst.py`, its own specialist.
"""

import asyncio

from agentic.data.base import DataProvider
from agentic.schemas.earnings import EarningsReport
from agentic.tools.earnings import (
    get_analyst_grades,
    get_earnings_day_moves,
    get_earnings_history,
    get_peer_earnings_comparison,
)
_FIELDS = (
    "latest_period_date",
    "latest_eps_actual",
    "latest_eps_estimated",
    "latest_eps_surprise_pct",
    "latest_revenue_actual",
    "latest_revenue_estimated",
    "latest_revenue_surprise_pct",
    "next_earnings_date",
)


async def analyze_earnings(provider: DataProvider, symbol: str) -> EarningsReport:
    history, grades, peer_comparison = await asyncio.gather(
        get_earnings_history(symbol), get_analyst_grades(symbol), get_peer_earnings_comparison(symbol)
    )

    report_dates = [q["date"] for q in history.get("quarterly_history", []) if q.get("date")]
    price_moves, price_data_source = await get_earnings_day_moves(provider, symbol, report_dates)
    quarterly_history = [
        {**q, "price_reaction_pct": price_moves.get(q["date"])} for q in history.get("quarterly_history", [])
    ]
    # Earnings/grades are always FMP direct (tools/earnings.py); the price
    # reaction comes through the provider fallback chain, so its actual
    # source can vary run to run.
    sources = {"fmp"}
    if price_data_source:
        sources.add(price_data_source)
    data_source = ", ".join(sorted(sources))

    missing = [field for field in _FIELDS if history.get(field) is None]
    caveats = []
    if history.get("quarters_analyzed", 0) == 0:
        caveats.append("No reported earnings history available")
    elif missing:
        caveats.append(f"Missing fields: {', '.join(missing)}")
    if history.get("quarters_analyzed", 0) < 4:
        caveats.append(f"Only {history.get('quarters_analyzed', 0)} quarters of data available")
    if not grades.get("analyst_grades"):
        caveats.append("No analyst grade history available")
    if len(peer_comparison) <= 1:
        caveats.append("No direct peers found for comparison")

    confidence = 1.0 - 0.1 * len(missing)
    confidence -= 0.3 if history.get("quarters_analyzed", 0) == 0 else 0.0
    confidence = max(0.0, round(confidence, 2))

    trend = history.get("trend", "stable")
    if history.get("quarters_analyzed", 0) == 0:
        summary = f"{symbol}: no reported earnings history available."
    else:
        summary = (
            f"{symbol}: {trend} earnings trend. Latest ({history.get('latest_period_date')}): "
            f"EPS {history.get('latest_eps_actual')} vs est. {history.get('latest_eps_estimated')} "
            f"({history.get('latest_eps_surprise_pct')}% surprise), beat streak "
            f"{history.get('eps_beat_streak')} quarters."
        )

    return EarningsReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        data_source=data_source,
        latest_period_date=history.get("latest_period_date"),
        latest_eps_actual=history.get("latest_eps_actual"),
        latest_eps_estimated=history.get("latest_eps_estimated"),
        latest_eps_surprise_pct=history.get("latest_eps_surprise_pct"),
        latest_revenue_actual=history.get("latest_revenue_actual"),
        latest_revenue_estimated=history.get("latest_revenue_estimated"),
        latest_revenue_surprise_pct=history.get("latest_revenue_surprise_pct"),
        eps_beat_streak=history.get("eps_beat_streak", 0),
        quarters_analyzed=history.get("quarters_analyzed", 0),
        quarterly_history=quarterly_history,
        analyst_grades=grades.get("analyst_grades", []),
        upgrade_count=grades.get("upgrade_count", 0),
        downgrade_count=grades.get("downgrade_count", 0),
        peer_comparison=peer_comparison,
        next_earnings_date=history.get("next_earnings_date"),
        trend=trend,
        summary=summary,
    )
