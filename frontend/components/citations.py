import streamlit as st

from components.text import escape_dollars


def render_filing_citations(citations: list) -> None:
    """Each insight followed by an expander with the filing it came from and
    the verbatim excerpt — the excerpt is what was retrieved from the 10-K,
    not something the LLM wrote, so a reader can check the insight against it.
    """
    for c in citations:
        if isinstance(c, str):
            # Cached results from before sources were tracked: plain strings.
            st.markdown(f"- {escape_dollars(c)}")
            continue
        st.markdown(f"- {escape_dollars(c['insight'])}")
        label = f"Source: {c['filing_type'] or 'filing'}, filed {c['filing_date'] or 'date unknown'}"
        with st.expander(label):
            st.caption(escape_dollars(c["excerpt"]))
