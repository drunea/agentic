import streamlit as st
import streamlit.components.v1 as components

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.specialist_page import render_specialist_page
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Technical Charts", layout="wide")
hide_skills_nudge()
st.title("Technical Charts")

symbol = symbol_input()


def _render(report: dict) -> None:
    st.subheader(f"Trend: {report['trend'].upper()}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("RSI(14)", report.get("rsi_14"))
    col2.metric("MACD", report.get("macd"))
    col3.metric("SMA(20)", report.get("sma_20"))
    col4.metric("EMA(20)", report.get("ema_20"))

    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **RSI(14)** (Relative Strength Index) — momentum oscillator (0-100) measuring "
            "the speed/magnitude of recent price moves. Above 55 leans bullish, below 45 leans "
            "bearish; the middle band is treated as inconclusive and doesn't vote either way.\n"
            "- **MACD** (12, 26, 9) — difference between the 12- and 26-period EMAs, compared "
            "against its own 9-period signal line. MACD above the signal line leans bullish, "
            "below leans bearish (a momentum-shift signal, not a price level).\n"
            "- **SMA(20)** / **EMA(20)** — 20-day simple and exponential moving averages. "
            "Price trading above either leans bullish, below leans bearish; EMA reacts faster "
            "to recent price moves than SMA since it weights recent days more heavily.\n"
            "- **Bollinger Bands(20, 2)** — a band 2 standard deviations above/below the 20-day "
            "SMA. Price closing at/above the upper band leans bullish, at/below the lower band "
            "leans bearish (not shown as its own tile above, but included in the Trend vote "
            "below).\n\n"
            "**Trend** is a weighted vote across all 5 signals above (price vs. SMA20, price vs. "
            "EMA20, MACD vs. signal, RSI, price vs. Bollinger Bands) — majority bullish votes "
            "call it *bullish*, majority bearish call it *bearish*, and a tie (or too few "
            "signals available) calls it *neutral*. Deterministic threshold logic, computed "
            "in Python — no LLM involved."
        )


render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="technical",
    render_result=_render,
)


def _render_tradingview_chart(symbol: str) -> None:
    """Embedded via `components.v1.html` (a plain one-way HTML/JS iframe),
    not the stateful `st.components.v2.component()` API used elsewhere in
    this app — this widget takes a fixed config at render time and never
    talks back to Streamlit, so the plain iframe embed is the simpler,
    correct tool.

    Deliberately independent from the specialist section above — different
    data source entirely (TradingView's own feed, not FMP), used only for
    the interactive chart/drawing-tools UX that would be very costly to
    replicate with Plotly. `allow_symbol_change` is the safety net for a
    bare ticker TradingView can't uniquely resolve on its own.

    `st.components.v1.html` renders a fixed-size iframe — it does NOT
    auto-size to content, so `height=` must be passed explicitly even
    though the widget's own `autosize` fills whatever height it's given.
    """
    html = f"""
    <style>
      /* `autosize: true` below needs a container with an actual resolved
      pixel height — a bare `height:100%` on the div alone doesn't work
      unless every ancestor (html, body) also has an explicit height, a
      classic CSS percentage-height gotcha. */
      html, body {{ height: 100%; margin: 0; padding: 0; }}
      #tradingview_widget {{ height: 100%; width: 100%; }}
    </style>
    <div id="tradingview_widget"></div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
    new TradingView.widget({{
      "autosize": true,
      "symbol": "{symbol}",
      "interval": "D",
      "timezone": "Etc/UTC",
      "theme": "dark",
      "style": "1",
      "locale": "en",
      "enable_publishing": false,
      "hide_top_toolbar": false,
      "hide_side_toolbar": false,
      "allow_symbol_change": true,
      "studies": ["MASimple@tv-basicstudies", "RSI@tv-basicstudies"],
      "container_id": "tradingview_widget"
    }});
    </script>
    """
    components.html(html, height=900)


if symbol:
    st.subheader("Chart")
    _render_tradingview_chart(symbol)
