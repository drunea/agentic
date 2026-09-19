"""Multi-specialist UI: one row per specialist (name/status/refresh
checkbox) at the top of the page inside a shared form, one "Analyze
selected" button, individual result sections rendered below. Same
convention as components/specialist_page.py's single-specialist pattern,
generalized to N specialists sharing one Analyze click.
"""

from collections.abc import Callable

import streamlit as st

from components.model_info import fetch_model_info, format_data_source, format_model_info
from components.specialist_page import fetch_company, humanize_age, poll_refresh_lock, start_refresh


def render_specialist_group(
    *,
    api_url: str,
    symbol: str,
    specialists: list[str],
    render_results: dict[str, Callable[[dict], None]],
    poll_seconds: int = 5,
) -> None:
    if not symbol:
        return

    company = fetch_company(api_url, symbol)
    if company is None:
        return

    symbol_kind = company.get("symbol_kind")
    if symbol_kind in ("etf", "fund"):
        st.info(
            f"**{symbol}** is {'an ETF' if symbol_kind == 'etf' else 'a fund'} — none of these "
            "specialists are built for funds yet (they assume an operating company's own "
            "financial statements/earnings), so nothing runs for it."
        )
        return

    model_info = fetch_model_info(api_url)
    locked = company.get("is_refreshing", False)

    st.subheader("Specialists")
    with st.form(f"specialists_form_{'_'.join(specialists)}"):
        selected: list[str] = []
        for name in specialists:
            entry = company["specialists"].get(name)
            if entry is None:
                continue
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.write(f"**{name.replace('_', ' ').title()}**")
            data_source = format_data_source(entry.get("result"))
            col2.caption(
                f"{entry['status']} — {humanize_age(entry['updated_at'])} · "
                f"Model: {format_model_info(model_info.get(name))}"
                + (f" · Data: {data_source}" if data_source else "")
            )
            checked = col3.checkbox("refresh", value=entry["is_expired"], key=f"grp_{name}", disabled=locked)
            if checked:
                selected.append(name)
        submitted = st.form_submit_button("Analyze selected", disabled=locked)

    if locked:
        st.caption("A refresh is running for this symbol (started from another page) — waiting for it to finish.")
        poll_refresh_lock(api_url, symbol, poll_seconds, key=f"lock_group_{'_'.join(specialists)}")

    if submitted and selected:
        start_refresh(api_url, symbol, {"specialists": selected})

    for name in specialists:
        entry = company["specialists"].get(name)
        if entry is None:
            continue
        st.divider()
        if entry["status"] in ("pending", "running"):
            st.info(f"{name.replace('_', ' ').title()}: {entry['status']} — auto-refreshes below when done.")
        elif entry["status"] == "error":
            st.error(f"{name.replace('_', ' ').title()}: Analysis failed: {entry['error']}")
        elif entry["status"] == "done":
            render_results[name](entry["result"])
        else:
            st.caption(f"{name.replace('_', ' ').title()}: not analyzed yet — check the box above and click Analyze.")

    _poll_while_pending(api_url, symbol, specialists, company, poll_seconds)


def _poll_while_pending(
    api_url: str, symbol: str, specialists: list[str], company: dict, poll_seconds: int
) -> None:
    """Same pattern as specialist_page.py/1_Stock_Analysis.py's pending-poll
    helpers: check ONCE, outside any fragment, whether anything is actually
    pending, using the caller's own already-fetched snapshot rather than
    fetching again (avoids a race against that fetch).
    """
    if not any(
        company["specialists"].get(name, {}).get("status") in ("pending", "running") for name in specialists
    ):
        return

    @st.fragment(run_every=poll_seconds, key=f"poll_group_{'_'.join(specialists)}")
    def _fragment() -> None:
        inner = fetch_company(api_url, symbol)
        if inner is None:
            return
        pending = [
            name for name in specialists if inner["specialists"].get(name, {}).get("status") in ("pending", "running")
        ]
        # Rerunning on every tick (not just once `pending` is empty) means
        # each specialist's result shows as soon as it individually
        # finishes, instead of every specialist appearing to complete at
        # the same instant once the slowest one is done. The outer guard
        # above already ensures this fragment only exists while something
        # is genuinely pending, so it can't loop forever once idle.
        if pending:
            st.info(f"Still running: {', '.join(pending)} — this updates automatically when ready.")
        st.rerun()

    _fragment()
