import numpy as np
import pandas as pd

from agentic.data.base import DataProvider

TRADING_DAYS_PER_YEAR = 252


async def get_performance_metrics(
    provider: DataProvider, symbol: str, benchmark: str = "SPY"
) -> dict:
    """Multi-horizon returns and Sharpe/Sortino ratios for `symbol`, plus a
    1-year benchmark return for context.
    """
    symbol_history = await provider.get_history(symbol, period="1y")
    data_source = symbol_history[0].get("_provider", "") if symbol_history else ""
    symbol_closes = _closes(symbol_history)
    benchmark_closes = _closes(await provider.get_history(benchmark, period="1y"))

    if len(symbol_closes) < 30:
        return {
            "has_data": False,
            "data_source": data_source,
            "return_1mo": None,
            "return_3mo": None,
            "return_6mo": None,
            "return_1y": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "benchmark_symbol": benchmark,
            "benchmark_return_1y": None,
        }

    returns = np.diff(symbol_closes) / symbol_closes[:-1]

    def horizon_return(days: int) -> float | None:
        if len(symbol_closes) <= days:
            return None
        return round(float(symbol_closes[-1] / symbol_closes[-days - 1] - 1) * 100, 2)

    mean_daily = returns.mean()
    std_daily = returns.std(ddof=1)
    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else None

    sharpe = (mean_daily / std_daily) * np.sqrt(TRADING_DAYS_PER_YEAR) if std_daily else None
    sortino = (
        (mean_daily / downside_std) * np.sqrt(TRADING_DAYS_PER_YEAR) if downside_std else None
    )

    benchmark_return_1y = None
    if len(benchmark_closes) > 1:
        benchmark_return_1y = round(
            float(benchmark_closes[-1] / benchmark_closes[0] - 1) * 100, 2
        )

    return {
        "has_data": True,
        "data_source": data_source,
        "return_1mo": horizon_return(21),
        "return_3mo": horizon_return(63),
        "return_6mo": horizon_return(126),
        "return_1y": horizon_return(len(symbol_closes) - 1),
        "sharpe_ratio": round(float(sharpe), 2) if sharpe is not None else None,
        "sortino_ratio": round(float(sortino), 2) if sortino is not None else None,
        "benchmark_symbol": benchmark,
        "benchmark_return_1y": benchmark_return_1y,
    }


def _closes(history: list[dict]) -> np.ndarray:
    df = pd.DataFrame(history)
    if df.empty:
        return np.array([])
    df.columns = [str(c).lower() for c in df.columns]
    return df["close"].astype(float).to_numpy()
