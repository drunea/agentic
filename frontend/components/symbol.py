"""Symbol text input that survives both a full page reload and navigating
between pages.

A raw browser reload (e.g. from a `<meta refresh>` auto-poll) starts a
brand new Streamlit session and resets every widget to its default —
`st.query_params` survives that, since the value lives in the URL rather
than in session state, which gets wiped.

`st.session_state`, on the other hand, IS shared across every page in a
multipage app for one browser session — `st.query_params` is NOT (each
page has its own URL/route, so its query params are independent). Reading
from `st.session_state` first gives cross-page persistence while keeping
`st.query_params` in sync for the reload case above.
"""

import streamlit as st


def symbol_input(default: str = "AAPL") -> str:
    current = st.session_state.get("symbol") or st.query_params.get("symbol", default)
    value = st.text_input("Symbol", value=current).strip().upper()
    if value:
        st.session_state["symbol"] = value
        if value != st.query_params.get("symbol"):
            st.query_params["symbol"] = value
    return value
