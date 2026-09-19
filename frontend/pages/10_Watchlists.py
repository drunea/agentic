import httpx
import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL

st.set_page_config(page_title="Watchlists", layout="wide")
hide_skills_nudge()
st.title("Watchlists")
st.caption(
    "The screener columns below show whatever's already cached from Stock Analysis (Technical, "
    "Risk) — opening this page never triggers a fresh analysis; visit a symbol's own page to "
    "refresh it."
)

_TREND_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
_RISK_EMOJI = {"low": "🟢", "moderate": "🟡", "high": "🔴"}
_ZONE_EMOJI = {"safe": "🟢", "grey": "🟡", "distress": "🔴"}

with st.form("new_watchlist", clear_on_submit=True):
    name = st.text_input("Name")
    symbols_raw = st.text_input("Symbols (comma-separated, optional)")
    submitted = st.form_submit_button("Create")
    if submitted and name:
        symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
        httpx.post(f"{API_URL}/watchlists", json={"name": name, "symbols": symbols}, timeout=10)
        st.rerun()

response = httpx.get(f"{API_URL}/watchlists", timeout=10)
watchlists = response.json() if response.status_code == 200 else []

if not watchlists:
    st.write("No watchlists yet.")

for wl in watchlists:
    st.divider()
    col1, col2 = st.columns([5, 1])
    col1.subheader(wl["name"])
    if col2.button("Delete list", key=f"del-wl-{wl['id']}"):
        httpx.delete(f"{API_URL}/watchlists/{wl['id']}", timeout=10)
        st.rerun()

    with st.form(f"add-symbol-{wl['id']}", clear_on_submit=True):
        c1, c2 = st.columns([4, 1])
        new_symbol = c1.text_input("Add symbol", key=f"add-symbol-input-{wl['id']}", label_visibility="collapsed", placeholder="Add symbol (e.g. AAPL)")
        add_submitted = c2.form_submit_button("Add")
        if add_submitted and new_symbol.strip():
            httpx.post(f"{API_URL}/watchlists/{wl['id']}/items", json={"symbol": new_symbol.strip()}, timeout=10)
            st.rerun()

    if not wl["items"]:
        st.caption("No symbols yet.")
        continue

    screener_resp = httpx.get(f"{API_URL}/watchlists/{wl['id']}/screener", timeout=10)
    screener = screener_resp.json() if screener_resp.status_code == 200 else []

    for row in screener:
        c1, c2, c3, c4, c5 = st.columns([1.5, 1.5, 2, 2.5, 0.7])
        c1.write(f"**{row['symbol']}**")
        if row.get("symbol_kind") in ("etf", "fund"):
            c2.write("—")
            kind_label = "ETF" if row["symbol_kind"] == "etf" else "Fund"
            c3.write(f"🏦 {kind_label} — not supported")
            c4.write("—")
        else:
            c2.write(f"{row['price']:.2f}" if row.get("price") is not None else "—")
            trend = row.get("technical_trend")
            c3.write(f"{_TREND_EMOJI.get(trend, '⚪')} {trend or 'not analyzed'}")
            risk_level = row.get("risk_level")
            z = row.get("altman_z_score")
            zone = row.get("altman_zone")
            risk_bit = f"{_RISK_EMOJI.get(risk_level, '⚪')} {risk_level or 'n/a'}"
            z_bit = f" · Z-Score {z} {_ZONE_EMOJI.get(zone, '')}" if z is not None else ""
            c4.write(risk_bit + z_bit)
        if c5.button("✕", key=f"del-item-{row['item_id']}", help="Remove from list"):
            httpx.delete(f"{API_URL}/watchlists/{wl['id']}/items/{row['item_id']}", timeout=10)
            st.rerun()
