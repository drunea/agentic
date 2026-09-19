import asyncio

from agentic.data.fmp_client import fmp_get
from agentic.tools.company_profile import get_company_profile

# Rough sector-level benchmarks (order-of-magnitude approximations, not a
# live benchmark data feed) — deliberately small/approximate and expandable
# incrementally. R&D-to-revenue %, revenue growth %, and gross margin % are
# blended estimates across each FMP sector (11 sectors — see
# tools/company_profile.py's sector list).
_SECTOR_BENCHMARKS: dict[str, dict[str, float]] = {
    "Technology": {"rd_pct": 9.0, "growth_pct": 8.0, "margin_pct": 50.0},
    "Healthcare": {"rd_pct": 8.0, "growth_pct": 6.0, "margin_pct": 50.0},
    "Communication Services": {"rd_pct": 6.0, "growth_pct": 5.0, "margin_pct": 45.0},
    "Consumer Cyclical": {"rd_pct": 2.0, "growth_pct": 5.0, "margin_pct": 30.0},
    "Consumer Defensive": {"rd_pct": 1.0, "growth_pct": 3.0, "margin_pct": 30.0},
    "Industrials": {"rd_pct": 3.0, "growth_pct": 4.0, "margin_pct": 28.0},
    "Financial Services": {"rd_pct": 1.0, "growth_pct": 4.0, "margin_pct": 40.0},
    "Energy": {"rd_pct": 1.0, "growth_pct": 3.0, "margin_pct": 25.0},
    "Basic Materials": {"rd_pct": 1.5, "growth_pct": 3.0, "margin_pct": 25.0},
    "Real Estate": {"rd_pct": 0.2, "growth_pct": 3.0, "margin_pct": 45.0},
    "Utilities": {"rd_pct": 0.3, "growth_pct": 2.0, "margin_pct": 35.0},
}
_DEFAULT_BENCHMARK = {"rd_pct": 4.0, "growth_pct": 4.0, "margin_pct": 35.0}


def _sub_score(value: float | None, benchmark: float, sensitivity: float) -> float:
    """50 = exactly at benchmark; +/- `sensitivity` points per 1-unit gap, clamped to [0, 100]."""
    if value is None:
        return 50.0
    return max(0.0, min(100.0, 50.0 + (value - benchmark) * sensitivity))


def _score_disruption(
    rd_pct: float | None, growth_pct: float | None, margin_pct: float | None, benchmark: dict
) -> tuple[float, str, float]:
    """Weighted composite (R&D intensity 35%, revenue growth 40%, gross
    margin 25%) vs. sector benchmark — mirrors gsaini's disruption_metrics.py
    weighting. Growth is compared at its current level, not year-over-year
    acceleration (we don't fetch enough history for that) — a known,
    documented simplification, not an oversight.
    """
    rd_score = _sub_score(rd_pct, benchmark["rd_pct"], sensitivity=5.0)
    growth_score = _sub_score(growth_pct, benchmark["growth_pct"], sensitivity=5.0)
    margin_score = _sub_score(margin_pct, benchmark["margin_pct"], sensitivity=2.0)

    composite = round(0.35 * rd_score + 0.40 * growth_score + 0.25 * margin_score, 1)

    if composite >= 65:
        posture = "disruptor"
    elif composite <= 35:
        posture = "vulnerable"
    else:
        posture = "neutral"

    risk_score = round(max(0.0, min(1.0, 1 - composite / 100)), 2)
    return composite, posture, risk_score


async def get_innovation_intensity(symbol: str) -> dict:
    """R&D-as-%-of-revenue, revenue growth, and gross margin for `symbol`,
    scored against a sector benchmark — computed in plain Python, not left
    to the LLM.
    """
    income, growth, profile = await asyncio.gather(
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, limit=1),
        asyncio.to_thread(fmp_get, "financial-growth", symbol=symbol, limit=1),
        get_company_profile(symbol),
    )
    income0 = income[0] if isinstance(income, list) and income else {}
    growth0 = growth[0] if isinstance(growth, list) and growth else {}

    revenue = income0.get("revenue")
    rd_expense = income0.get("researchAndDevelopmentExpenses")
    gross_profit = income0.get("grossProfit")

    rd_to_revenue_pct = round(100 * rd_expense / revenue, 2) if revenue and rd_expense else None
    gross_margin_pct = round(100 * gross_profit / revenue, 2) if revenue and gross_profit else None

    revenue_growth = growth0.get("revenueGrowth")
    revenue_growth_pct = round(100 * revenue_growth, 2) if revenue_growth is not None else None

    sector = profile.get("sector")
    benchmark = _SECTOR_BENCHMARKS.get(sector, _DEFAULT_BENCHMARK)
    composite, posture, risk_score = _score_disruption(
        rd_to_revenue_pct, revenue_growth_pct, gross_margin_pct, benchmark
    )

    return {
        "sector": sector,
        "rd_to_revenue_pct": rd_to_revenue_pct,
        "revenue_growth_pct": revenue_growth_pct,
        "gross_margin_pct": gross_margin_pct,
        "rd_expense_growth_pct": (
            round(100 * growth0["rdexpenseGrowth"], 2)
            if growth0.get("rdexpenseGrowth") is not None
            else None
        ),
        "benchmark": benchmark,
        "disruption_score_100": composite,
        "disruption_posture": posture,
        "disruption_risk_score": risk_score,
    }
