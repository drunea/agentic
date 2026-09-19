import plotly.graph_objects as go
import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.specialist_page import render_specialist_page
from components.symbol import symbol_input
from components.text import escape_dollars, format_money

_BEAT_COLOR = "#2ecc71"
_MISS_COLOR = "#e74c3c"
_ESTIMATE_COLOR = "#7f8c8d"

st.set_page_config(page_title="Earnings Comparison", layout="wide")
hide_skills_nudge()
st.title("Earnings Comparison")
st.caption("Latest reported quarter's actual-vs-estimate, plus the beat streak leading into it.")

symbol = symbol_input()


def _render_quarterly_history(quarters: list[dict]) -> None:
    if not quarters:
        return

    st.subheader("Quarterly history")
    # `quarters` is most-recent-first (matches tools/earnings.py); charts and
    # tables read left-to-right as oldest-to-newest, so reverse for display.
    ordered = list(reversed(quarters))
    dates = [q.get("date") or "" for q in ordered]

    eps_actual = [q.get("eps_actual") for q in ordered]
    eps_estimated = [q.get("eps_estimated") for q in ordered]
    eps_colors = [
        _BEAT_COLOR if (a is not None and e is not None and a >= e) else _MISS_COLOR
        for a, e in zip(eps_actual, eps_estimated)
    ]

    fig = go.Figure()
    fig.add_bar(name="EPS Estimated", x=dates, y=eps_estimated, marker_color=_ESTIMATE_COLOR)
    fig.add_bar(name="EPS Actual", x=dates, y=eps_actual, marker_color=eps_colors)
    fig.update_layout(
        barmode="group",
        yaxis_title="EPS ($/share)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        {
            "Date": dates,
            "EPS Actual": eps_actual,
            "EPS Estimated": eps_estimated,
            "EPS Surprise %": [q.get("eps_surprise_pct") for q in ordered],
            "Revenue Actual": [format_money(q.get("revenue_actual")) for q in ordered],
            "Revenue Estimated": [format_money(q.get("revenue_estimated")) for q in ordered],
            "Revenue Surprise %": [q.get("revenue_surprise_pct") for q in ordered],
            "Price reaction (next day) %": [q.get("price_reaction_pct") for q in ordered],
        },
        hide_index=True,
        use_container_width=True,
    )


_ACTION_ICON = {"upgrade": "⬆️", "downgrade": "⬇️", "maintain": "➡️"}


def _render_analyst_grades(grades: list[dict], upgrade_count: int, downgrade_count: int) -> None:
    if not grades:
        return

    st.subheader("Analyst guidance")
    col1, col2, col3 = st.columns(3)
    col1.metric("Upgrades", upgrade_count)
    col2.metric("Downgrades", downgrade_count)
    col3.metric("Ratings shown", len(grades))

    st.dataframe(
        {
            "Date": [g.get("date") or "" for g in grades],
            "Action": [
                f"{_ACTION_ICON.get(g.get('action'), '')} {g.get('action') or ''}".strip() for g in grades
            ],
            "Firm": [g.get("grading_company") or "" for g in grades],
            "Previous grade": [g.get("previous_grade") or "" for g in grades],
            "New grade": [g.get("new_grade") or "" for g in grades],
        },
        hide_index=True,
        use_container_width=True,
    )


def _render_peer_comparison(peers: list[dict]) -> None:
    if len(peers) <= 1:
        return

    st.subheader("Peer comparison")
    st.caption("Latest reported quarter's YoY growth pace — target symbol first, then direct peers.")
    st.dataframe(
        {
            "Symbol": [("★ " if p.get("is_target") else "") + p["symbol"] for p in peers],
            "Latest period": [p.get("latest_period_date") or "" for p in peers],
            "EPS actual": [p.get("latest_eps_actual") for p in peers],
            "EPS growth YoY %": [p.get("eps_growth_yoy_pct") for p in peers],
            "Revenue actual": [format_money(p.get("latest_revenue_actual")) for p in peers],
            "Revenue growth YoY %": [p.get("revenue_growth_yoy_pct") for p in peers],
        },
        hide_index=True,
        use_container_width=True,
    )


def _render(report: dict) -> None:
    st.subheader(f"Trend: {report['trend'].upper()}")
    st.caption(f"Latest period: {report.get('latest_period_date') or '—'}")

    col1, col2 = st.columns(2)
    col1.metric("EPS actual ($/share)", report.get("latest_eps_actual"))
    col1.metric("EPS estimated ($/share)", report.get("latest_eps_estimated"))
    col1.metric(
        "EPS surprise (actual vs. estimate)",
        f"{report.get('latest_eps_surprise_pct')}%"
        if report.get("latest_eps_surprise_pct") is not None
        else None,
    )
    col2.metric("Revenue actual (total company)", format_money(report.get("latest_revenue_actual")))
    col2.metric("Revenue estimated (total company)", format_money(report.get("latest_revenue_estimated")))
    col2.metric(
        "Revenue surprise (actual vs. estimate)",
        f"{report.get('latest_revenue_surprise_pct')}%"
        if report.get("latest_revenue_surprise_pct") is not None
        else None,
    )

    col3, col4, col5 = st.columns(3)
    col3.metric("EPS beat streak", report.get("eps_beat_streak"))
    col4.metric("Quarters analyzed", report.get("quarters_analyzed"))
    col5.metric("Next earnings date", report.get("next_earnings_date") or "—")

    _render_quarterly_history(report.get("quarterly_history") or [])
    _render_analyst_grades(
        report.get("analyst_grades") or [], report.get("upgrade_count", 0), report.get("downgrade_count", 0)
    )
    _render_peer_comparison(report.get("peer_comparison") or [])

    st.subheader("Summary")
    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **EPS/Revenue surprise** — actual vs. analyst-estimated, as a % gap: "
            "`(actual - estimated) / |estimated|`.\n"
            "- **EPS beat streak** — consecutive most-recent quarters (working backward) with a "
            "positive EPS surprise; stops counting at the first miss.\n"
            "- **Trend** — compares the average EPS surprise of the 2 most recent quarters against "
            "the prior 2: a gap beyond ±2 points is improving/deteriorating, a sign flip between "
            "them is mixed, otherwise stable. With fewer than 4 quarters of data, falls back to the "
            "beat streak alone. Fully computed in Python — no LLM involved anywhere in this "
            "specialist.\n"
            "- **Analyst guidance** — individual analyst rating changes (upgrade/downgrade/maintain), "
            "the closest forward-looking signal available on the current FMP plan (quarterly "
            "earnings-estimate revision history is paywalled).\n"
            "- **Price reaction (next day) %** — % change from the closing price at-or-before the "
            "report date to the close on the next trading day after it. FMP's earnings data doesn't "
            "flag before/after-market timing, so this is a fixed definition, not exact reaction "
            "timing.\n"
            "- **Peer growth YoY %** — latest reported quarter's actual EPS/revenue vs. the SAME "
            "quarter one year earlier (not vs. the prior quarter), to avoid seasonality noise. Peers "
            "come from FMP's own peer-group data (`stock-peers`), up to 5."
        )


render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="earnings",
    render_result=_render,
)
