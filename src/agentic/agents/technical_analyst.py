"""Plain Python, no LLM.

Indicators are standard formulas (pandas_ta), and trend classification from
them is industry convention (SMA/EMA crossover, RSI thresholds, MACD vs
signal), not a judgment call — even the "signals disagree" case is handled
by simple weighted voting across the 5 indicators below, no LLM reasoning
needed.
"""

from agentic.data.base import DataProvider
from agentic.schemas.technical import TechnicalReport
from agentic.tools.technical_indicators import get_technical_indicators

_NUMERIC_FIELDS = (
    "last_close",
    "rsi_14",
    "macd",
    "macd_signal",
    "sma_20",
    "ema_20",
    "bb_upper",
    "bb_lower",
)


def _classify_trend(indicators: dict) -> str:
    """Weighted vote across 5 independent signals — resolves disagreement
    (e.g. RSI overbought but MACD hasn't crossed yet) by majority rather
    than letting any single indicator dominate.
    """
    last_close = indicators.get("last_close")
    rsi_14 = indicators.get("rsi_14")
    macd = indicators.get("macd")
    macd_signal = indicators.get("macd_signal")
    sma_20 = indicators.get("sma_20")
    ema_20 = indicators.get("ema_20")
    bb_upper = indicators.get("bb_upper")
    bb_lower = indicators.get("bb_lower")

    score = 0
    votes = 0

    if last_close is not None and sma_20 is not None:
        score += 1 if last_close > sma_20 else -1
        votes += 1
    if last_close is not None and ema_20 is not None:
        score += 1 if last_close > ema_20 else -1
        votes += 1
    if macd is not None and macd_signal is not None:
        score += 1 if macd > macd_signal else -1
        votes += 1
    if rsi_14 is not None and (rsi_14 > 55 or rsi_14 < 45):
        score += 1 if rsi_14 > 55 else -1
        votes += 1
    if last_close is not None and bb_upper is not None and bb_lower is not None:
        if last_close >= bb_upper:
            score += 1
        elif last_close <= bb_lower:
            score -= 1
        votes += 1

    if votes == 0 or score == 0:
        return "neutral"
    return "bullish" if score > 0 else "bearish"


async def analyze_technical(provider: DataProvider, symbol: str) -> TechnicalReport:
    indicators = await get_technical_indicators(provider, symbol)

    missing = [field for field in _NUMERIC_FIELDS if indicators.get(field) is None]
    caveats = []
    if missing:
        caveats.append(f"Missing fields: {', '.join(missing)}")
    if not indicators:
        caveats.append("No price history returned — indicators unavailable")

    confidence = max(0.0, round(1.0 - 0.1 * len(missing), 2))
    trend = _classify_trend(indicators)

    last_close = indicators.get("last_close")
    rsi_14 = indicators.get("rsi_14")
    summary = (
        f"{symbol}: {trend} trend. RSI(14)={rsi_14}, MACD={indicators.get('macd')} "
        f"vs signal={indicators.get('macd_signal')}, price={last_close} vs "
        f"SMA(20)={indicators.get('sma_20')}."
        if indicators
        else f"{symbol}: no technical data available."
    )

    return TechnicalReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        trend=trend,
        summary=summary,
        data_source=indicators.get("data_source", ""),
        **{field: indicators.get(field) for field in _NUMERIC_FIELDS},
    )
