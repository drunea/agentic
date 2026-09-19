from agentic.data.base import DataProvider


def normalize_price_history(history: list[dict]) -> list[dict]:
    """FMP and yfinance use different column casing/date formats — this gives
    callers (charts, indicators) one consistent shape.
    """
    normalized = []
    for row in history:
        lower = {str(k).lower(): v for k, v in row.items()}
        normalized.append(
            {
                "date": str(lower.get("date"))[:10],
                "open": lower.get("open"),
                "high": lower.get("high"),
                "low": lower.get("low"),
                "close": lower.get("close"),
                "volume": lower.get("volume"),
            }
        )
    return normalized


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


async def get_market_snapshot(provider: DataProvider, symbol: str) -> dict:
    """Quote + a short recent-history point count, used by the Data Collector
    to prove data actually came back before other agents build on it.
    Prices rounded to cents, volume/market cap to whole units — the raw
    yfinance/FMP floats carry 10+ meaningless decimal places.
    """
    quote = await provider.get_quote(symbol)
    history = await provider.get_history(symbol, period="1mo")
    return {
        "price": _round(quote.get("price"), 2),
        "previous_close": _round(quote.get("previousClose"), 2),
        "day_high": _round(quote.get("dayHigh"), 2),
        "day_low": _round(quote.get("dayLow"), 2),
        "year_high": _round(quote.get("yearHigh"), 2),
        "year_low": _round(quote.get("yearLow"), 2),
        "volume": _round(quote.get("volume"), 0),
        "market_cap": _round(quote.get("marketCap"), 0),
        "history_points": len(history),
    }
