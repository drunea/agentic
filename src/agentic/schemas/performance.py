from pydantic import BaseModel, Field

from agentic.schemas.common import AgentFinding


class Trade(BaseModel):
    entry_date: str
    exit_date: str | None = Field(default=None, description="None if still open at the end of the backtest window.")
    entry_price: float
    exit_price: float
    return_pct: float
    days_held: int


class EquityPoint(BaseModel):
    date: str
    equity: float  # normalized, 1.0 = starting value


class BacktestResult(BaseModel):
    strategy: str
    total_return_pct: float | None = None
    cagr_pct: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown_pct: float | None = None
    recovery_days: int | None = Field(default=None, description="None if never recovered by the end of the window.")
    trade_count: int
    trades: list[Trade] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)


class PerformanceReport(AgentFinding):
    symbol: str
    return_1mo: float | None = None
    return_3mo: float | None = None
    return_6mo: float | None = None
    return_1y: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    benchmark_symbol: str
    benchmark_return_1y: float | None = None
    backtests: list[BacktestResult] = Field(
        default_factory=list, description="One entry per strategy — SMA crossover, RSI mean-reversion, buy & hold (symbol), buy & hold (benchmark)."
    )
    summary: str
