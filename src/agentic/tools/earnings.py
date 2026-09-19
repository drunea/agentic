import asyncio
from datetime import date

from agentic.data.base import DataProvider
from agentic.data.fmp_client import fmp_get
from agentic.tools.market_data import normalize_price_history
from agentic.tools.peer_discovery import find_peers

_MAX_PEERS_COMPARED = 5


def _surprise_pct(actual: float | None, estimated: float | None) -> float | None:
    if actual is None or estimated is None or estimated == 0:
        return None
    return round(100 * (actual - estimated) / abs(estimated), 2)


def _classify_trend(surprises: list[float | None], beat_streak: int) -> str:
    """Compares the average EPS surprise of the 2 most recent quarters against
    the prior 2 (most-recent-first `surprises`) — a widening/positive gap is
    'improving', a shrinking/negative one is 'deteriorating'. With fewer than
    4 quarters of data, falls back to the beat streak alone.
    """
    valid = [s for s in surprises if s is not None]
    if len(valid) < 2:
        return "stable"

    recent_avg = sum(valid[:2]) / len(valid[:2])
    prior = valid[2:4]

    if not prior:
        if beat_streak >= 2:
            return "improving"
        if beat_streak == 0:
            return "deteriorating"
        return "stable"

    prior_avg = sum(prior) / len(prior)
    delta = recent_avg - prior_avg

    if delta > 2:
        return "improving"
    if delta < -2:
        return "deteriorating"
    if (recent_avg > 0) != (prior_avg > 0):
        return "mixed"
    return "stable"


async def get_earnings_history(symbol: str, quarters: int = 8) -> dict:
    """Last `quarters` reported quarters (EPS/revenue actual vs estimate) plus
    the next scheduled report date, via FMP's earnings endpoint. Surprise %
    and beat-streak are computed here in plain Python — not left to the LLM.
    """
    raw = await asyncio.to_thread(fmp_get, "earnings", symbol=symbol, limit=quarters + 4)
    rows = raw if isinstance(raw, list) else []

    today = date.today().isoformat()
    future = [r for r in rows if r.get("date", "") > today]
    reported = [r for r in rows if r.get("date", "") <= today and r.get("epsActual") is not None]

    next_earnings_date = min((r["date"] for r in future), default=None)

    reported_sorted = sorted(reported, key=lambda r: r["date"], reverse=True)[:quarters]

    beat_streak = 0
    for row in reported_sorted:
        surprise = _surprise_pct(row.get("epsActual"), row.get("epsEstimated"))
        if surprise is not None and surprise > 0:
            beat_streak += 1
        else:
            break

    latest = reported_sorted[0] if reported_sorted else {}
    eps_surprises = [
        _surprise_pct(row.get("epsActual"), row.get("epsEstimated")) for row in reported_sorted
    ]

    quarterly_history = [
        {
            "date": row.get("date"),
            "eps_actual": row.get("epsActual"),
            "eps_estimated": row.get("epsEstimated"),
            "eps_surprise_pct": _surprise_pct(row.get("epsActual"), row.get("epsEstimated")),
            "revenue_actual": row.get("revenueActual"),
            "revenue_estimated": row.get("revenueEstimated"),
            "revenue_surprise_pct": _surprise_pct(row.get("revenueActual"), row.get("revenueEstimated")),
        }
        for row in reported_sorted
    ]

    return {
        "latest_period_date": latest.get("date"),
        "latest_eps_actual": latest.get("epsActual"),
        "latest_eps_estimated": latest.get("epsEstimated"),
        "latest_eps_surprise_pct": _surprise_pct(latest.get("epsActual"), latest.get("epsEstimated")),
        "latest_revenue_actual": latest.get("revenueActual"),
        "latest_revenue_estimated": latest.get("revenueEstimated"),
        "latest_revenue_surprise_pct": _surprise_pct(
            latest.get("revenueActual"), latest.get("revenueEstimated")
        ),
        "eps_beat_streak": beat_streak,
        "quarters_analyzed": len(reported_sorted),
        "quarterly_history": quarterly_history,
        "next_earnings_date": next_earnings_date,
        "trend": _classify_trend(eps_surprises, beat_streak),
    }


async def get_analyst_grades(symbol: str, limit: int = 25) -> dict:
    """Analyst rating actions (upgrade/downgrade/maintain), most-recent-first
    — the closest FMP has to a forward-guidance signal (no earnings-estimate
    revision history available on this plan, see fmp_client.py's
    analyst-estimates note).

    `limit` is sliced here in Python, not trusted as a query param — verified
    live that FMP's `grades` endpoint ignores `limit` entirely on this plan
    and always returns full history (hundreds of rows, years back).
    """
    raw = await asyncio.to_thread(fmp_get, "grades", symbol=symbol)
    rows = raw[:limit] if isinstance(raw, list) else []

    grades = [
        {
            "date": row.get("date"),
            "grading_company": row.get("gradingCompany"),
            "previous_grade": row.get("previousGrade"),
            "new_grade": row.get("newGrade"),
            "action": row.get("action"),
        }
        for row in rows
    ]
    return {
        "analyst_grades": grades,
        "upgrade_count": sum(1 for g in grades if g["action"] == "upgrade"),
        "downgrade_count": sum(1 for g in grades if g["action"] == "downgrade"),
    }


async def get_earnings_day_moves(
    provider: DataProvider, symbol: str, report_dates: list[str]
) -> tuple[dict[str, float | None], str]:
    """% price move from the close on (or immediately before) each report
    date to the close on the next trading day after it — FMP's earnings data
    has no before/after-market flag, so this is a fixed, explainable
    definition rather than a guess at exact market-reaction timing.

    Returns `({report_date: move_pct | None}, data_source)` — `move_pct` is
    None when the report date falls outside the fetched price-history window
    (too old, or too recent for a "next day" close to exist yet).
    `data_source` reflects whichever provider in the fallback chain actually
    answered `get_history` (e.g. "fmp"/"yfinance"), empty if history was
    empty.
    """
    if not report_dates:
        return {}, ""

    raw_history = await provider.get_history(symbol, period="2y")
    data_source = raw_history[0].get("_provider", "") if raw_history else ""
    bars = sorted(normalize_price_history(raw_history), key=lambda b: b["date"])
    dates = [b["date"] for b in bars]

    moves: dict[str, float | None] = {}
    for report_date in report_dates:
        # Last trading day at-or-before the report date (bisect_right - 1),
        # then the very next trading day after it.
        idx = _last_index_at_or_before(dates, report_date)
        if idx is None or idx + 1 >= len(bars):
            moves[report_date] = None
            continue
        before_close = bars[idx]["close"]
        after_close = bars[idx + 1]["close"]
        if before_close is None or after_close is None or before_close == 0:
            moves[report_date] = None
            continue
        moves[report_date] = round(100 * (after_close - before_close) / before_close, 2)

    return moves, data_source


def _last_index_at_or_before(sorted_dates: list[str], target: str) -> int | None:
    idx = None
    for i, d in enumerate(sorted_dates):
        if d <= target:
            idx = i
        else:
            break
    return idx


def _yoy_growth_pct(current: float | None, year_ago: float | None) -> float | None:
    if current is None or year_ago is None or year_ago == 0:
        return None
    return round(100 * (current - year_ago) / abs(year_ago), 2)


async def get_peer_earnings_comparison(symbol: str) -> list[dict]:
    """Latest-quarter revenue/EPS YoY growth pace for `symbol` and up to
    `_MAX_PEERS_COMPARED` direct peers (`tools/peer_discovery.py::find_peers`,
    FMP's `stock-peers`) — `symbol` itself is always the first row, so the
    table reads as "you vs. peers", not just a peer list.

    YoY, not QoQ: compares the latest reported quarter's actual EPS/revenue
    against the SAME quarter one year earlier (4 quarters back in
    `quarterly_history`, since results come in quarterly) — avoids the
    seasonality noise a quarter-over-quarter comparison would carry for most
    companies.
    """
    peers = await find_peers(symbol)
    symbols = [symbol] + [p for p in peers if p != symbol][:_MAX_PEERS_COMPARED]

    histories = await asyncio.gather(*(get_earnings_history(s, quarters=5) for s in symbols))

    rows = []
    for s, history in zip(symbols, histories):
        quarters = history.get("quarterly_history", [])
        latest = quarters[0] if quarters else {}
        year_ago = quarters[4] if len(quarters) >= 5 else {}
        rows.append(
            {
                "symbol": s,
                "is_target": s == symbol,
                "latest_period_date": latest.get("date"),
                "latest_eps_actual": latest.get("eps_actual"),
                "eps_growth_yoy_pct": _yoy_growth_pct(latest.get("eps_actual"), year_ago.get("eps_actual")),
                "latest_revenue_actual": latest.get("revenue_actual"),
                "revenue_growth_yoy_pct": _yoy_growth_pct(
                    latest.get("revenue_actual"), year_ago.get("revenue_actual")
                ),
            }
        )
    return rows
