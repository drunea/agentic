import httpx
import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.specialist_group import render_specialist_group
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Sentiment & News", layout="wide")
hide_skills_nudge()
st.title("Sentiment & News")

symbol = symbol_input()


def _render(report: dict) -> None:
    st.subheader("Sentiment")
    st.caption(f"Tone: {report['tone'].upper()}")
    col1, col2 = st.columns(2)
    col1.metric("Average VADER score", report.get("average_score"))
    col2.metric("Articles analyzed", report.get("article_count"))

    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **Average VADER score** — VADER (a rule-based sentiment lexicon) compound score "
            "per headline, averaged across the most recent articles fetched. Ranges -1 (most "
            "negative) to +1 (most positive).\n"
            "- **Tone** — the average score thresholded: above +0.05 is positive, below -0.05 is "
            "negative, in between is neutral. Deterministic, computed in Python — the LLM only "
            "copies this number through and writes the summary, it doesn't judge sentiment itself."
        )

    st.subheader("Recent headlines")
    for headline in report.get("headlines", []):
        title = escape_dollars(headline.get("title", ""))
        url = headline.get("url")
        site = headline.get("site")
        line = f"[{title}]({url})" if url else title
        if site:
            line += f" — *{site}*"
        st.markdown(f"- {line}")


def _render_earnings_call(report: dict) -> None:
    st.subheader("Earnings Call Analysis")
    if not report.get("call_date"):
        st.caption(escape_dollars(report.get("summary", "No earnings call transcript available.")))
        return

    st.caption(f"Q{report['quarter']} {report['year']} — Tone: {report['management_tone'].upper()}")
    st.caption(f"Call date: {report.get('call_date')}")

    if report.get("key_topics"):
        st.write("**Key topics:** " + ", ".join(escape_dollars(t) for t in report["key_topics"]))

    st.write(escape_dollars(report["summary"]))
    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))

    with st.expander("What each factor measures"):
        st.markdown(
            "- **Management tone** — overall tone leadership conveyed on the call, judged by an "
            "LLM reading the full transcript (prepared remarks + Q&A), not derived from any "
            "numeric formula.\n"
            "- **Evasive statements** — specific Q&A exchanges where an executive's response to a "
            "direct analyst question reads as a dodge, deflection, or vague non-answer. Flagged "
            "only when genuinely present — an empty list is a valid result, not a missing one."
        )

    evasive = report.get("evasive_statements") or []
    st.subheader(f"Evasive statements ({len(evasive)})")
    if not evasive:
        st.caption("None flagged for this call.")
    for item in evasive:
        if item.get("question"):
            st.markdown(f"**Q:** {escape_dollars(item['question'])}")
        st.markdown(f"**Response:** {escape_dollars(item.get('response_excerpt', ''))}")
        st.caption(escape_dollars(item.get("why_evasive", "")))
        st.divider()


render_specialist_group(
    api_url=API_URL,
    symbol=symbol,
    specialists=["sentiment", "earnings_call"],
    render_results={"sentiment": _render, "earnings_call": _render_earnings_call},
)


def _sentiment_emoji(label: str | None) -> str:
    if not label:
        return ""
    label = label.lower()
    if "positive" in label:
        return "🟢"
    if "negative" in label:
        return "🔴"
    return "⚪"


def _render_market_news(symbol: str) -> None:
    """No specialist behind this — no LLM. Backed by a shared GLOBAL news
    cache table, refreshed on its own TTL independent of any symbol — this
    endpoint just filters that cache by `symbol` + recency (last 24h)
    server-side; it does NOT call FMP itself on every page view. If nothing
    turns up for this symbol in the last day, the whole section is skipped
    rather than shown empty.
    """
    try:
        response = httpx.get(f"{API_URL}/market-news/{symbol}", timeout=30)
        response.raise_for_status()
        items = response.json()
    except httpx.HTTPError as exc:
        st.error(f"Could not load market news: {exc}")
        return

    if not items:
        return  # nothing for this symbol in the last 24h — skip the section

    st.header("Market News")
    st.caption(
        "From the shared market-wide news feed, filtered to this symbol and to the last 24h — "
        "sentiment label/reasoning computed by the source provider per article, not by this app."
    )
    for item in items:
        provider = item.get("provider")
        line = (
            f"{_sentiment_emoji(item.get('sentiment'))} "
            f"[{escape_dollars(item.get('title') or '')}]({item.get('url')}) "
            f"— *{item.get('site') or ''}*"
            + (f" · {provider.capitalize()}" if provider else "")
        )
        st.markdown(line)
        reasoning = item.get("sentiment_reasoning")
        if reasoning:
            with st.expander("Why this sentiment?"):
                st.caption(escape_dollars(reasoning))


if symbol:
    _render_market_news(symbol)
