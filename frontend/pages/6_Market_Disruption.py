import streamlit as st

from components.chrome import hide_skills_nudge
from components.citations import render_filing_citations
from components.config import API_URL
from components.specialist_page import render_specialist_page
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Market Disruption", layout="wide")
hide_skills_nudge()
st.title("Market Disruption")

symbol = symbol_input()


def _render(report: dict) -> None:
    st.subheader(f"Posture: {report['disruption_posture'].upper()}")
    col1, col2, col3 = st.columns(3)
    col1.metric("Disruption risk score", report.get("disruption_risk_score"))
    col2.metric(
        "R&D / revenue",
        f"{report.get('rd_to_revenue_pct')}%" if report.get("rd_to_revenue_pct") is not None else None,
    )
    col3.metric(
        "Revenue growth",
        f"{report.get('revenue_growth_pct')}%" if report.get("revenue_growth_pct") is not None else None,
    )

    col_opp, col_threat = st.columns(2)
    with col_opp:
        st.subheader("Opportunities")
        for item in report.get("opportunities", []):
            st.write(f"- {escape_dollars(item)}")
    with col_threat:
        st.subheader("Threats")
        for item in report.get("threats", []):
            st.write(f"- {escape_dollars(item)}")

    filing_insights = report.get("filing_insights") or []
    if filing_insights:
        st.subheader("From the company's 10-K")
        render_filing_citations(filing_insights)

    st.subheader("Summary")
    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **Disruption risk score** — 1 minus the disruption score (0-100) scaled to 0-1: "
            "higher means more vulnerable to disruption, not causing it.\n"
            "- **R&D / revenue** — R&D expense as a % of revenue, from the latest annual income "
            "statement.\n"
            "- **Revenue growth** — latest annual revenue growth %.\n"
            "- **Posture** — a weighted composite score (R&D intensity 35% + revenue growth 40% + "
            "gross margin 25%) compared against a sector-level benchmark, computed in Python, not "
            "judged by an LLM: ≥65 is 'disruptor', ≤35 is 'vulnerable', otherwise 'neutral'. The "
            "benchmark is a small hand-built approximation per FMP sector, not a live data feed.\n"
            "- **Opportunities / Threats** — the only LLM-written part: grounded in the actual "
            "recent headlines fetched (current information the formula above can't know about), "
            "not derived from the score.\n"
            "- **From the company's 10-K** — also LLM-written, but from the company's own latest "
            "10-K rather than headlines: competition and technology-risk points, each shown with "
            "the filing type/date and the exact retrieved excerpt it's based on so you can verify "
            "it. The 10-K is downloaded automatically the first time a symbol is analyzed."
        )


render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="disruption",
    render_result=_render,
)
