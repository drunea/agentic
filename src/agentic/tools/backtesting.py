import pandas as pd
import pandas_ta as ta

from agentic.data.base import DataProvider

SHORT_WINDOW = 20
LONG_WINDOW = 50
RSI_LENGTH = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
TRADING_DAYS_PER_YEAR = 252


def _sma_crossover_position(close: pd.Series) -> pd.Series:
    """Long when SMA(20) > SMA(50), flat otherwise."""
    sma_short = close.rolling(SHORT_WINDOW).mean()
    sma_long = close.rolling(LONG_WINDOW).mean()
    # Trade on the day after a crossover signal, not the signal day itself —
    # using today's close to decide today's position would be lookahead bias.
    return (sma_short > sma_long).astype(int).shift(1).fillna(0)


def _rsi_mean_reversion_position(close: pd.Series) -> pd.Series:
    """Enter long when RSI(14) crosses below 30 (oversold), exit when it
    crosses back above 70 (overbought) — stateful (depends on whether
    already in a position), unlike the SMA crossover's plain comparison.
    """
    rsi = ta.rsi(close, length=RSI_LENGTH)
    position = []
    in_position = False
    for value in rsi:
        if pd.notna(value):
            if not in_position and value < RSI_OVERSOLD:
                in_position = True
            elif in_position and value > RSI_OVERBOUGHT:
                in_position = False
        position.append(1 if in_position else 0)
    return pd.Series(position, index=close.index).shift(1).fillna(0)


def _buy_and_hold_position(close: pd.Series) -> pd.Series:
    return pd.Series(1, index=close.index)


def _extract_trades(dates: list[str], close: pd.Series, position: pd.Series) -> list[dict]:
    """One entry per contiguous stretch where `position` is 1, bounded by
    entry (0->1) and exit (1->0). A position still open at the end of the
    window is included with `exit_date=None`, marked-to-market at the last
    available close.
    """
    trades = []
    entry_idx: int | None = None
    pos_list = position.tolist()
    for i, cur in enumerate(pos_list):
        prev = pos_list[i - 1] if i > 0 else 0
        if prev == 0 and cur == 1:
            entry_idx = i
        elif prev == 1 and cur == 0 and entry_idx is not None:
            trades.append(_build_trade(dates, close, entry_idx, i - 1, still_open=False))
            entry_idx = None
    if entry_idx is not None:
        trades.append(_build_trade(dates, close, entry_idx, len(pos_list) - 1, still_open=True))
    return trades


def _build_trade(dates: list[str], close: pd.Series, entry_idx: int, exit_idx: int, still_open: bool) -> dict:
    entry_price = float(close.iloc[entry_idx])
    exit_price = float(close.iloc[exit_idx])
    return {
        "entry_date": dates[entry_idx],
        "exit_date": None if still_open else dates[exit_idx],
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "return_pct": round((exit_price / entry_price - 1) * 100, 2),
        "days_held": exit_idx - entry_idx,
    }


def _compute_backtest(strategy_name: str, dates: list[str], close: pd.Series, position: pd.Series) -> dict:
    daily_returns = close.pct_change().fillna(0)
    strategy_returns = daily_returns * position

    equity_curve = (1 + strategy_returns).cumprod()
    final_equity = float(equity_curve.iloc[-1])
    total_return_pct = round((final_equity - 1) * 100, 2)

    start_date = pd.to_datetime(dates[0])
    end_date = pd.to_datetime(dates[-1])
    years = max((end_date - start_date).days / 365.25, 1 / 365.25)
    cagr_pct = round((final_equity ** (1 / years) - 1) * 100, 2) if final_equity > 0 else None

    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown_pct = round(float(drawdown.min()) * 100, 2)

    # Recovery: days from the trough back to the equity level it was
    # falling from — None if the window ends before that happens.
    trough_pos = int(drawdown.to_numpy().argmin())
    peak_level = running_max.iloc[trough_pos]
    recovery_days = None
    for j in range(trough_pos + 1, len(equity_curve)):
        if equity_curve.iloc[j] >= peak_level:
            recovery_days = j - trough_pos
            break

    mean_r, std_r = strategy_returns.mean(), strategy_returns.std(ddof=1)
    sharpe_ratio = round(float((mean_r / std_r) * (TRADING_DAYS_PER_YEAR**0.5)), 2) if std_r else None
    downside = strategy_returns[strategy_returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else None
    sortino_ratio = (
        round(float((mean_r / downside_std) * (TRADING_DAYS_PER_YEAR**0.5)), 2) if downside_std else None
    )
    calmar_ratio = (
        round(cagr_pct / abs(max_drawdown_pct), 2)
        if cagr_pct is not None and max_drawdown_pct not in (None, 0)
        else None
    )

    trades = _extract_trades(dates, close, position)

    return {
        "strategy": strategy_name,
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "max_drawdown_pct": max_drawdown_pct,
        "recovery_days": recovery_days,
        "trade_count": len(trades),  # not diff()-based — that misses a position already open at day 1
        "trades": trades,
        "equity_curve": [{"date": d, "equity": round(float(e), 4)} for d, e in zip(dates, equity_curve)],
    }


def _close_and_dates(history: list[dict]) -> tuple[pd.Series, list[str]]:
    df = pd.DataFrame(history)
    df.columns = [str(c).lower() for c in df.columns]
    df = df.sort_values("date").reset_index(drop=True)
    # A missing/bad tick (verified live: yfinance returned a NaN close for
    # SPY's very first row in a 5y window) would otherwise propagate into
    # every downstream calculation (returns, equity curve, trade prices) as
    # NaN — dropped here, at ingestion, rather than patched per-field later.
    df = df[df["close"].notna()].reset_index(drop=True)
    close = df["close"].astype(float)
    dates = df["date"].astype(str).str[:10].tolist()
    return close, dates


async def run_backtests(provider: DataProvider, symbol: str, period: str = "5y", benchmark: str = "SPY") -> dict:
    """Runs 3 strategies on `symbol` (SMA(20/50) crossover, RSI(14)
    mean-reversion, buy & hold) plus a buy & hold run on `benchmark` — the
    benchmark comparison is the whole point: an active strategy that
    doesn't beat simply holding the asset (after the fact that its own
    Buy & Hold curve is shown alongside it) isn't a signal worth trusting.
    """
    history = await provider.get_history(symbol, period=period)
    data_source = history[0].get("_provider", "") if history else ""
    if not history or len(history) < LONG_WINDOW + 10:
        return {"strategies": [], "data_source": data_source}

    close, dates = _close_and_dates(history)

    strategies = [
        ("sma_crossover_20_50", _sma_crossover_position(close)),
        ("rsi_mean_reversion_14", _rsi_mean_reversion_position(close)),
        (f"buy_and_hold_{symbol}", _buy_and_hold_position(close)),
    ]
    results = [_compute_backtest(name, dates, close, position) for name, position in strategies]

    bench_history = await provider.get_history(benchmark, period=period)
    if bench_history and len(bench_history) >= 2:
        bench_close, bench_dates = _close_and_dates(bench_history)
        results.append(
            _compute_backtest(
                f"buy_and_hold_{benchmark}", bench_dates, bench_close, _buy_and_hold_position(bench_close)
            )
        )

    return {"strategies": results, "data_source": data_source}
