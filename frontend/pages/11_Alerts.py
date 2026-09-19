import httpx
import streamlit as st
import streamlit.components.v1 as components

from components.chrome import hide_skills_nudge
from components.config import API_URL, WS_API_URL

st.set_page_config(page_title="Alerts", layout="wide")
hide_skills_nudge()
st.title("Alerts")
st.caption(
    "Checked server-side every 30s (no broker — one polling loop per open WebSocket "
    "connection). Price alerts use a live quote; the rest read whatever's already cached from "
    "Stock Analysis (Technical/Risk/Earnings) — a symbol never analyzed there just never "
    "triggers. The live feed below only shows alerts that trigger while this page is open."
)

_TRIGGER_LABEL = {
    "price_above": "Price ≥ threshold",
    "price_below": "Price ≤ threshold",
    "rsi_oversold": "RSI(14) < 30 (oversold)",
    "price_below_sma20": "Price < SMA(20)",
    "altman_distress": "Altman Z-Score < 2.99 (grey/distress zone)",
    "earnings_soon": "Earnings report within 5 days",
}
_NEEDS_THRESHOLD = {"price_above", "price_below"}

with st.form("new_alert", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    symbol = col1.text_input("Symbol").strip().upper()
    trigger_type = col2.selectbox("Trigger", list(_TRIGGER_LABEL.keys()), format_func=lambda t: _TRIGGER_LABEL[t])
    # A form's own widgets don't rerun the script on change (only on
    # submit), so this can't conditionally hide itself based on the
    # selectbox above — shown always, with a caption instead of hiding it.
    threshold = col3.number_input("Threshold price (price alerts only)", min_value=0.0, step=0.01)
    submitted = st.form_submit_button("Create alert")
    if submitted and symbol:
        body = {"symbol": symbol, "trigger_type": trigger_type}
        if trigger_type in _NEEDS_THRESHOLD:
            body["threshold"] = threshold
        httpx.post(f"{API_URL}/alerts", json=body, timeout=10)
        st.rerun()

response = httpx.get(f"{API_URL}/alerts", timeout=10)
alerts = response.json() if response.status_code == 200 else []

if not alerts:
    st.write("No alerts configured yet.")

for alert in alerts:
    col1, col2 = st.columns([4, 1])
    label = _TRIGGER_LABEL.get(alert["trigger_type"], alert["trigger_type"])
    threshold_bit = f" ({alert['threshold']})" if alert.get("threshold") is not None else ""
    col1.write(f"**{alert['symbol']}** — {label}{threshold_bit}")
    if col2.button("Delete", key=f"del-alert-{alert['id']}"):
        httpx.delete(f"{API_URL}/alerts/{alert['id']}", timeout=10)
        st.rerun()

st.subheader("Live feed")
components.html(
    f"""
    <div id="log" style="font-family: monospace; font-size: 0.85rem; height: 220px;
                overflow-y: auto; border: 1px solid #444; border-radius: 6px; padding: 8px;">
      connecting...
    </div>
    <script>
      const log = document.getElementById("log");
      log.innerHTML = "";
      function addLine(text) {{
        const line = document.createElement("div");
        line.textContent = new Date().toLocaleTimeString() + " — " + text;
        log.prepend(line);
      }}
      try {{
        const ws = new WebSocket("{WS_API_URL}/ws/alerts");
        ws.onopen = () => addLine("connected — watching active alerts");
        ws.onmessage = (event) => {{
          const data = JSON.parse(event.data);
          const {{alert_id, symbol, trigger_type, ...detail}} = data;
          const details = Object.entries(detail).map(([k, v]) => `${{k}}=${{v}}`).join(", ");
          addLine(`${{symbol}} ${{trigger_type}} — ${{details}}`);
        }};
        ws.onerror = () => addLine("connection error");
        ws.onclose = () => addLine("disconnected");
      }} catch (e) {{
        addLine("failed to connect: " + e);
      }}
    </script>
    """,
    height=250,
)
