import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.specialist_page import render_specialist_page
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Risk Analysis", layout="wide")
hide_skills_nudge()
st.title("Risk Analysis")

symbol = symbol_input()

_ZONE_EMOJI = {"safe": "🟢", "grey": "🟡", "distress": "🔴"}
_CRITERION_LABEL = {
    "positive_net_income": "Positive net income",
    "positive_operating_cash_flow": "Positive operating cash flow",
    "roa_improving": "ROA improving YoY",
    "cfo_exceeds_net_income": "Operating cash flow exceeds net income",
    "leverage_decreasing": "Long-term debt / assets decreasing YoY",
    "current_ratio_improving": "Current ratio improving YoY",
    "no_new_shares_issued": "No new shares issued",
    "gross_margin_improving": "Gross margin improving YoY",
    "asset_turnover_improving": "Asset turnover improving YoY",
}


def _render_market_risk(report: dict) -> None:
    st.subheader(f"Risk Level: {report['risk_level'].upper()}")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        f"VaR ({report['confidence_level']*100:.0f}%, {report['horizon_days']}d)",
        f"{report.get('var_pct')}%" if report.get("var_pct") is not None else None,
    )
    col2.metric(
        "CVaR", f"{report.get('cvar_pct')}%" if report.get("cvar_pct") is not None else None
    )
    col3.metric(
        f"{report['rate_environment_series']} yield",
        f"{report.get('rate_environment_latest')}%"
        if report.get("rate_environment_latest") is not None
        else None,
    )

    st.caption(
        "Monte Carlo VaR/CVaR via historical simulation "
        f"({report.get('confidence_level', 0)*100:.0f}% confidence, "
        f"{report.get('horizon_days')}-day horizon)."
    )

    with st.expander("What each factor measures"):
        st.markdown(
            "- **VaR (Value at Risk)** — the loss threshold not expected to be exceeded more than "
            "(100 - confidence)% of the time over the given horizon. E.g. a 95% VaR of -8.5% means: "
            "in 95% of simulated outcomes, the loss over the horizon was no worse than 8.5%.\n"
            "- **CVaR (Conditional VaR / Expected Shortfall)** — the *average* loss in the worst "
            "(100 - confidence)% of simulated outcomes, i.e. how bad it gets specifically in the "
            "tail VaR already flags — always at least as severe as VaR itself.\n"
            "- Both computed via historical-simulation Monte Carlo: 10,000 simulated paths built by "
            "resampling (with replacement) the symbol's own actual daily returns over the last year "
            "— no assumption of a normal distribution.\n"
            "- **Risk level** — thresholded directly from VaR magnitude (industry convention): "
            "under 5% is low, 5-15% is moderate, over 15% is high.\n"
            "- **Treasury yield (FRED)** — the 10-Year Treasury Constant Maturity Rate, a standard "
            "proxy for the broad risk-free rate environment — context, not an input to the VaR/CVaR "
            "calculation itself."
        )


def _render_credit_risk(report: dict) -> None:
    z_score = report.get("altman_z_score")
    zone = report.get("altman_zone")
    f_score = report.get("piotroski_f_score")
    period = report.get("credit_risk_period_date")

    st.caption(f"Latest annual period: {period or '—'}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Altman Z-Score",
        z_score,
        f"{_ZONE_EMOJI.get(zone, '')} {zone or ''}".strip() if zone else None,
    )
    col2.metric(
        "Piotroski F-Score",
        f"{f_score}/9" if f_score is not None else None,
    )
    col3.metric(
        "Net Debt / EBITDA",
        report.get("net_debt_to_ebitda"),
    )
    col4.metric(
        "Interest Coverage",
        report.get("interest_coverage_ratio"),
    )

    components = report.get("altman_components") or {}
    if components:
        with st.expander("Altman Z-Score components"):
            st.dataframe(
                {
                    "Component": [
                        "Working Capital / Total Assets",
                        "Retained Earnings / Total Assets",
                        "EBIT / Total Assets",
                        "Market Cap / Total Liabilities",
                        "Sales / Total Assets",
                    ],
                    "Value": [
                        components.get("working_capital_to_assets"),
                        components.get("retained_earnings_to_assets"),
                        components.get("ebit_to_assets"),
                        components.get("market_cap_to_liabilities"),
                        components.get("sales_to_assets"),
                    ],
                },
                hide_index=True,
                use_container_width=True,
            )

    criteria = report.get("piotroski_criteria") or {}
    if criteria:
        with st.expander(f"Piotroski F-Score criteria ({report.get('piotroski_criteria_determined', 0)}/9 determined)"):
            for key, passed in criteria.items():
                icon = "✅" if passed is True else "❌" if passed is False else "➖"
                st.write(f"{icon} {_CRITERION_LABEL.get(key, key)}")

    with st.expander("What each factor measures"):
        st.markdown(
            "- **Altman Z-Score** — a weighted composite of 5 balance-sheet/income-statement ratios "
            "predicting bankruptcy risk over a ~2-year horizon: Z > 2.99 is the safe zone, 1.81-2.99 "
            "is the grey zone, Z < 1.81 is the distress zone. A fixed published formula (Altman, "
            "1968), not a judgment call.\n"
            "- **Piotroski F-Score (0-9)** — counts how many of 9 year-over-year financial-health "
            "signals improved (profitability, leverage/liquidity, operating efficiency) — higher is "
            "healthier. Needs 2 annual periods; a criterion that can't be determined from available "
            "data contributes neither a pass nor a fail, and the expander above shows exactly how "
            "many of the 9 were actually determined.\n"
            "- **Net Debt / EBITDA** — how many years of current earnings (before interest/tax/"
            "D&A) it would take to pay off net debt; negative means more cash than debt.\n"
            "- **Interest Coverage Ratio** — EBIT ÷ interest expense; how many times over the "
            "company can cover its interest payments from operating earnings."
        )


def _render(report: dict) -> None:
    tab_market, tab_credit = st.tabs(["Market Risk", "Balance Sheet & Solvency"])
    with tab_market:
        _render_market_risk(report)
    with tab_credit:
        _render_credit_risk(report)

    st.subheader("Summary")
    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))


render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="risk",
    render_result=_render,
)
