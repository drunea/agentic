"""Page-chrome tweaks that aren't covered by `.streamlit/config.toml` options
— injected per-page since this app uses the classic `pages/` auto-discovery
multipage layout (no `st.navigation` entry point to inject from once)."""

import streamlit as st


def hide_skills_nudge() -> None:
    """Hides the "Help agents write better apps / Install the official
    Streamlit skills" toast (`data-testid="stSkillsNudge"`, confirmed by
    reading the actual selector out of Streamlit's compiled JS bundle,
    `static/js/index.*.js`) — not covered by `toolbarMode` and, per the
    user's live report, its own "Don't show again" button didn't reliably
    stick across reloads.
    """
    st.markdown(
        '<style>[data-testid="stSkillsNudge"] { display: none !important; }</style>',
        unsafe_allow_html=True,
    )
