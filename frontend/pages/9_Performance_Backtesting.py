import plotly.graph_objects as go
import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.specialist_page import render_specialist_page
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Performance & Backtesting", layout="wide")
hide_skills_nudge()
st.title("Performance & Backtesting")
st.caption(
    "Single-symbol performance metrics + 3 deterministic backtest strategies (SMA(20/50) "
    "crossover, RSI(14) mean-reversion, buy & hold) compared against buy & hold on the "
    "benchmark. Not full multi-asset portfolio optimization (Markowitz/efficient frontier) — "
    "deferred."
)

symbol = symbol_input()

_STRATEGY_LABEL = {
    "sma_crossover_20_50": "SMA(20/50) Crossover",
    "rsi_mean_reversion_14": "RSI(14) Mean-Reversion",
}


def _strategy_label(name: str, symbol: str, benchmark: str) -> str:
    if name == f"buy_and_hold_{symbol}":
        return f"Buy & Hold ({symbol})"
    if name == f"buy_and_hold_{benchmark}":
        return f"Buy & Hold ({benchmark}, benchmark)"
    return _STRATEGY_LABEL.get(name, name)


def _render_backtests(backtests: list[dict], symbol: str, benchmark: str) -> None:
    if not backtests:
        return

    st.subheader("Strategy comparison")
    labels = [_strategy_label(b["strategy"], symbol, benchmark) for b in backtests]
    st.dataframe(
        {
            "Strategy": labels,
            "Total return %": [b.get("total_return_pct") for b in backtests],
            "CAGR %": [b.get("cagr_pct") for b in backtests],
            "Sharpe": [b.get("sharpe_ratio") for b in backtests],
            "Sortino": [b.get("sortino_ratio") for b in backtests],
            "Calmar": [b.get("calmar_ratio") for b in backtests],
            "Max drawdown %": [b.get("max_drawdown_pct") for b in backtests],
            "Recovery (days)": [b.get("recovery_days") for b in backtests],
            "Trades": [b.get("trade_count") for b in backtests],
        },
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Equity curve")
    fig = go.Figure()
    for b, label in zip(backtests, labels):
        curve = b.get("equity_curve") or []
        if not curve:
            continue
        fig.add_scatter(
            x=[p["date"] for p in curve],
            y=[p["equity"] for p in curve],
            mode="lines",
            name=label,
        )
    fig.update_layout(
        yaxis_title="Equity (1.0 = starting value)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Trade log")
    selected_label = st.selectbox("Strategy", labels, key="perf_trade_log_strategy")
    selected = backtests[labels.index(selected_label)]
    trades = selected.get("trades") or []
    if not trades:
        st.caption("No trades for this strategy over the backtest window.")
    else:
        st.dataframe(
            {
                "Entry date": [t.get("entry_date") for t in trades],
                "Exit date": [t.get("exit_date") or "open" for t in trades],
                "Entry price": [t.get("entry_price") for t in trades],
                "Exit price": [t.get("exit_price") for t in trades],
                "Return %": [t.get("return_pct") for t in trades],
                "Days held": [t.get("days_held") for t in trades],
            },
            hide_index=True,
            use_container_width=True,
        )


def _render(report: dict) -> None:
    st.subheader("Returns")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("1mo", f"{report.get('return_1mo')}%" if report.get("return_1mo") is not None else None)
    col2.metric("3mo", f"{report.get('return_3mo')}%" if report.get("return_3mo") is not None else None)
    col3.metric("6mo", f"{report.get('return_6mo')}%" if report.get("return_6mo") is not None else None)
    col4.metric("1y", f"{report.get('return_1y')}%" if report.get("return_1y") is not None else None)

    col5, col6, col7 = st.columns(3)
    col5.metric("Sharpe", report.get("sharpe_ratio"))
    col6.metric("Sortino", report.get("sortino_ratio"))
    col7.metric(
        f"{report.get('benchmark_symbol')} 1y",
        f"{report.get('benchmark_return_1y')}%"
        if report.get("benchmark_return_1y") is not None
        else None,
    )

    _render_backtests(report.get("backtests") or [], report.get("symbol", ""), report.get("benchmark_symbol", "SPY"))

    st.subheader("Summary")
    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **CAGR (Compound Annual Growth Rate)** — the constant annual growth rate that "
            "would take the starting equity to the ending equity over the actual time span, "
            "`equity^(1/years) - 1`. More comparable across different time windows than total "
            "return.\n"
            "- **Sharpe ratio** — average return per unit of *total* volatility (annualized). "
            "Higher is better risk-adjusted return.\n"
            "- **Sortino ratio** — same idea as Sharpe, but only penalizes *downside* volatility "
            "— doesn't count upside swings against the strategy.\n"
            "- **Calmar ratio** — CAGR ÷ |Max Drawdown|. How much annual growth per unit of the "
            "worst peak-to-trough loss experienced — a return-vs-pain measure Sharpe/Sortino "
            "don't directly capture.\n"
            "- **Max drawdown** — the largest peak-to-trough decline in equity over the window.\n"
            "- **Recovery (days)** — trading days from the drawdown's trough back to the equity "
            "level it fell from; blank means it never recovered by the end of the window.\n"
            "- **Buy & Hold comparison** — the whole point of including it: an active strategy "
            "that doesn't beat simply holding the asset (or the benchmark) isn't a signal worth "
            "trusting, however good its own numbers look in isolation.\n"
            "- All of the above are fixed formulas computed in Python — no LLM judgment anywhere "
            "in this specialist. A narrative explaining *why* a strategy performed as it did would "
            "need the full daily price path as LLM context (hundreds+ of data points) for real "
            "cost and marginal benefit — deliberately not built; these numbers already tell the "
            "story."
        )


render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="performance",
    render_result=_render,
)
