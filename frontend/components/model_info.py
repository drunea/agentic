"""Which LLM (if any) runs a given specialist — static server config, not
per-symbol data, so cached once per browser session rather than refetched
on every rerun.
"""

import httpx
import streamlit as st


def fetch_model_info(api_url: str) -> dict:
    cache_key = f"_model_info_{api_url}"
    if cache_key not in st.session_state:
        try:
            response = httpx.get(f"{api_url}/specialists-info", timeout=10)
            response.raise_for_status()
            st.session_state[cache_key] = response.json()
        except httpx.HTTPError:
            st.session_state[cache_key] = {}
    return st.session_state[cache_key]


def format_model_info(info: dict | None) -> str:
    if not info:
        return "no LLM"
    backend = (info.get("backend") or "").capitalize()
    model = info.get("model") or ""
    return f"{backend}: {model}"


def format_data_source(result: dict | None) -> str:
    """Which provider actually served a specialist's underlying data for
    THIS result — e.g. "roic" vs "fmp" for Earnings Call — distinct from
    `format_model_info`, which reflects static .env config, not what a
    provider-fallback chain (see MARKET_NEWS_PROVIDER_ORDER/
    EARNINGS_CALL_PROVIDER_ORDER) actually used for this particular run.
    Empty string if the specialist's schema has no `data_source` field.
    """
    if not result:
        return ""
    source = result.get("data_source")
    if not source:
        return ""
    return ", ".join(part.strip().replace("_", " ").title() for part in source.split(","))
