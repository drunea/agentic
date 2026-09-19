import streamlit as st

from components.chrome import hide_skills_nudge
from components.citations import render_filing_citations
from components.config import API_URL
from components.specialist_page import fetch_company, render_specialist_page
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Valuation", layout="wide")
hide_skills_nudge()
st.title("Valuation")
st.caption(
    "Ratios, DCF fair value, peers, and SEC filing interpretation — the `valuation` specialist. "
    "Not the same as Fundamental Deep Dive (standardized financial statements + AFFO); this page "
    "is about what the company is worth, that one is about what it reported."
)

symbol = symbol_input()

status_slot = st.empty()


def _render(report: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("P/E (TTM)", report.get("pe_ratio"))
    col2.metric("P/B (TTM)", report.get("pb_ratio"))
    col3.metric("ROE", f"{report['roe']}%" if report.get("roe") is not None else None)
    col4.metric("FCF / share", report.get("fcf_per_share"))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **P/E (TTM)** — price / trailing-twelve-months earnings per share. Higher means the "
            "market is paying more per dollar of current earnings, usually pricing in faster "
            "expected growth (or overvaluation).\n"
            "- **P/B (TTM)** — price / book value per share. Below 1 can mean the market values the "
            "company at less than its stated net assets.\n"
            "- **ROE** — Net Income / Shareholders' Equity (same definition as the Capital Efficiency "
            "section on Fundamental Deep Dive).\n"
            "- **FCF / share** — Free Cash Flow / diluted shares outstanding — cash-based "
            "profitability per share, independent of accounting earnings."
        )

    st.subheader("DCF fair value")
    dcf = report.get("dcf") or {}
    fair_value = dcf.get("fair_value_per_share")

    # Current price comes from the data_collector specialist, piggybacked
    # on every refresh below (same pattern as Stock Analysis's Identity
    # Card) — valuation's own report has no price field, only the DCF
    # output, so the over/undervalued comparison is computed here at the
    # page level.
    dc_company = fetch_company(API_URL, symbol)
    dc_result = ((dc_company or {}).get("specialists", {}).get("data_collector") or {}).get("result") or {}
    price = dc_result.get("price")

    col1, col2, col3 = st.columns(3)
    col1.metric("Fair value / share", f"${fair_value:,.2f}" if fair_value is not None else None)
    col2.metric("Current price", f"${price:,.2f}" if price is not None else None)
    if fair_value is not None and price:
        gap_pct = (fair_value - price) / price * 100
        col3.metric(
            "Vs. current price",
            f"{'Undervalued' if gap_pct > 0 else 'Overvalued'} {abs(gap_pct):.1f}%",
        )
    else:
        col3.metric("Vs. current price", None)

    st.caption(f"Assumptions: WACC {dcf.get('wacc')}%, growth rate {dcf.get('growth_rate')}%")
    with st.expander("What each factor measures"):
        st.markdown(
            "- **Fair value / share** — simplified single-stage (Gordon-growth) DCF: projects free "
            "cash flow forward at a constant growth rate, discounts it back at WACC, forever. A "
            "deliberate simplification (no 3-scenario/multi-stage modeling yet) — treat it as a "
            "rough anchor, not a precise target.\n"
            "- **WACC** — same Weighted Average Cost of Capital computed for Capital Efficiency on "
            "Fundamental Deep Dive; the discount rate applied to projected cash flows here.\n"
            "- **Growth rate** — the constant perpetual growth rate assumed for cash flows beyond "
            "the current year. A single fixed-assumption DCF is highly sensitive to this input — "
            "small changes swing fair value substantially."
        )

    st.subheader("Peers")
    peers = report.get("peers") or []
    st.write(", ".join(peers) if peers else "No peers found.")

    st.subheader("Filing insights")
    st.caption(
        "LLM-written from passages retrieved out of the company's latest 10-K (downloaded "
        "automatically the first time a symbol is analyzed). Open a source to read the exact "
        "excerpt an insight is based on."
    )
    citations = report.get("filing_citations") or []
    if citations:
        render_filing_citations(citations)
    else:
        st.caption("No usable SEC filing insights for this symbol — see the caveats below for why.")

    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))


render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="valuation",
    render_result=_render,
    also_refresh=["data_collector"],
    status_slot=status_slot,
)
