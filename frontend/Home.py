import streamlit as st

from components.chrome import hide_skills_nudge

st.set_page_config(page_title="Financial Research Analyst Agent", layout="wide")
hide_skills_nudge()

st.title("Financial Research Analyst Agent")
st.write(
    "Use the sidebar to navigate: **Stock Analysis** (full 9-agent orchestrator run), "
    "single-specialist pages (Fundamental Deep Dive, Valuation, Technical, Sentiment, Risk, "
    "Performance, Disruption, Earnings), **Watchlists**, and **Alerts**."
)
st.caption(
    "Each symbol has one live snapshot per specialist, refreshed only when stale "
    "(or on demand) — not a new run every time. Navigate away any time; a refresh "
    "keeps going server-side and the page picks it back up when you return."
)
