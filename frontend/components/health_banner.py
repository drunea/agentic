import httpx
import streamlit as st

from components.text import escape_dollars


def render_specialist_health_warning(api_url: str) -> None:
    """Warns about specialists whose last several runs all failed — a single
    failed symbol already shows on its own page; this is the cross-symbol
    signal (expired API key, Ollama down) that otherwise only lives in the
    server log. Silent if the check itself can't be made: a health banner
    must never take the page down.
    """
    try:
        response = httpx.get(f"{api_url}/health/specialists", timeout=5)
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, ValueError):
        return

    for row in rows:
        if row["alerting"]:
            st.warning(
                escape_dollars(
                    f"**{row['specialist']}** has failed {row['consecutive_failures']} runs in a row "
                    f"(latest on {row['last_error_symbol']}): {row['last_error']}"
                )
            )
