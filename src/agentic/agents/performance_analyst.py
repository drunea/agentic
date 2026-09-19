"""Plain Python, no LLM.

Sharpe/Sortino/CAGR/Calmar/drawdown/recovery are standard formulas with one
correct answer — no judgment involved. A narrative explaining *why* a
backtest performed the way it did would need the full daily price path as
LLM context (hundreds to over a thousand data points) rather than these
already-synthesized summary stats — real cost for marginal value (LLMs read
raw numeric time series poorly and tend toward generic narration), so
deliberately not built. The numbers already tell the story: CAGR, Max
Drawdown, Sharpe/Sortino/Calmar, and the trade log are the full picture.
"""

from agentic.data.base import DataProvider
from agentic.schemas.performance import PerformanceReport
from agentic.tools.backtesting import run_backtests
from agentic.tools.performance import get_performance_metrics

_METRIC_FIELDS = (
    "return_1mo",
    "return_3mo",
    "return_6mo",
    "return_1y",
    "sharpe_ratio",
    "sortino_ratio",
    "benchmark_return_1y",
)


async def analyze_performance(provider: DataProvider, symbol: str) -> PerformanceReport:
    metrics = await get_performance_metrics(provider, symbol)
    backtest_result = await run_backtests(provider, symbol)
    backtests = backtest_result.get("strategies", [])

    has_metrics = metrics.get("has_data", False)
    missing_metrics = [field for field in _METRIC_FIELDS if metrics.get(field) is None] if has_metrics else list(_METRIC_FIELDS)

    caveats = []
    if not has_metrics:
        caveats.append("Insufficient price history for performance metrics")
    elif missing_metrics:
        caveats.append(f"Missing fields: {', '.join(missing_metrics)}")
    if not backtests:
        caveats.append("Insufficient price history for backtesting")

    confidence = 1.0
    confidence -= 0.5 if not has_metrics else 0.1 * len(missing_metrics)
    confidence -= 0.3 if not backtests else 0.0
    confidence = max(0.0, round(confidence, 2))

    benchmark_symbol = metrics.get("benchmark_symbol", "SPY")

    # Metrics and backtests each fetch price history independently (over
    # different windows — 1y vs 5y) through the provider fallback chain, so
    # their actual sources can differ.
    sources = set()
    for source in (metrics.get("data_source"), backtest_result.get("data_source")):
        if source:
            sources.add(source)
    data_source = ", ".join(sorted(sources))

    if has_metrics:
        summary = (
            f"{symbol}: 1y return {metrics.get('return_1y')}%, Sharpe {metrics.get('sharpe_ratio')}, "
            f"vs {benchmark_symbol} 1y {metrics.get('benchmark_return_1y')}%. "
        )
    else:
        summary = f"{symbol}: insufficient price history for performance metrics. "

    if backtests:
        best = max((b for b in backtests if b.get("cagr_pct") is not None), key=lambda b: b["cagr_pct"], default=None)
        if best:
            summary += (
                f"Best backtest strategy by CAGR: {best['strategy']} ({best['cagr_pct']}% CAGR, "
                f"max drawdown {best.get('max_drawdown_pct')}%)."
            )
    else:
        summary += "Insufficient price history for backtesting."

    return PerformanceReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        data_source=data_source,
        return_1mo=metrics.get("return_1mo"),
        return_3mo=metrics.get("return_3mo"),
        return_6mo=metrics.get("return_6mo"),
        return_1y=metrics.get("return_1y"),
        sharpe_ratio=metrics.get("sharpe_ratio"),
        sortino_ratio=metrics.get("sortino_ratio"),
        benchmark_symbol=benchmark_symbol,
        benchmark_return_1y=metrics.get("benchmark_return_1y"),
        backtests=backtests,
        summary=summary,
    )
