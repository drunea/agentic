"""Plain Python, no LLM.

A market-data snapshot is a pure passthrough: the numbers already fetched
by `get_market_snapshot` *are* the answer, there's no ambiguity to reason
over and no text to interpret. Routing this through an LLM only added
latency and a chance of the transcription step dropping a field.
"""

from agentic.data.base import DataProvider
from agentic.schemas.data_collector import DataCollectorReport
from agentic.tools.market_data import get_market_snapshot

_NUMERIC_FIELDS = (
    "price",
    "previous_close",
    "day_high",
    "day_low",
    "year_high",
    "year_low",
    "volume",
    "market_cap",
)


async def analyze_data_collector(provider: DataProvider, symbol: str) -> DataCollectorReport:
    snapshot = await get_market_snapshot(provider, symbol)

    missing = [field for field in _NUMERIC_FIELDS if snapshot.get(field) is None]
    caveats = []
    if missing:
        caveats.append(f"Missing fields: {', '.join(missing)}")
    if snapshot["history_points"] == 0:
        caveats.append("No recent price history returned")

    confidence = 1.0 - 0.1 * len(missing) - (0.3 if snapshot["history_points"] == 0 else 0.0)
    confidence = max(0.0, round(confidence, 2))

    price = snapshot.get("price")
    summary = (
        f"{symbol}: last price {price}, {snapshot['history_points']} recent history points."
        if price is not None
        else f"{symbol}: no price data returned."
    )

    return DataCollectorReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        summary=summary,
        **snapshot,
    )
