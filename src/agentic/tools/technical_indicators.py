import pandas as pd
import pandas_ta as ta

from agentic.data.base import DataProvider


async def get_technical_indicators(
    provider: DataProvider, symbol: str, period: str = "6mo"
) -> dict:
    """RSI(14), MACD(12,26,9), Bollinger Bands(20,2), SMA(20), EMA(20) from
    recent price history.
    """
    history = await provider.get_history(symbol, period=period)
    if not history:
        return {}
    data_source = history[0].get("_provider", "")

    df = pd.DataFrame(history)
    df.columns = [str(c).lower() for c in df.columns]
    if "close" not in df.columns:
        return {}

    close = df["close"]
    macd = ta.macd(close)
    bbands = ta.bbands(close, length=20)

    return {
        "last_close": _last(close),
        "rsi_14": _last(ta.rsi(close)),
        "macd": _last(macd["MACD_12_26_9"]) if macd is not None else None,
        "macd_signal": _last(macd["MACDs_12_26_9"]) if macd is not None else None,
        "sma_20": _last(ta.sma(close, length=20)),
        "ema_20": _last(ta.ema(close, length=20)),
        "bb_upper": _last(bbands["BBU_20_2.0_2.0"]) if bbands is not None else None,
        "bb_lower": _last(bbands["BBL_20_2.0_2.0"]) if bbands is not None else None,
        "data_source": data_source,
    }


def _last(series: "pd.Series | None") -> float | None:
    if series is None or series.empty:
        return None
    value = series.iloc[-1]
    # Raw pandas_ta floats carry 10+ meaningless decimal places once rendered.
    return None if pd.isna(value) else round(float(value), 2)
