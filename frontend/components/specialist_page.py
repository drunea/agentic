"""Shared UI pattern for the company_analysis architecture. There is no job
concept on the frontend: every page just asks "what's the current state for
this symbol" (GET /company/{symbol}, always instant) and, if the viewer
wants, triggers a refresh for specific specialists. The result IS the
cache — closing the tab or coming back tomorrow shows exactly what's
stored, with its own age, not a job someone else happened to run.
"""

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
import streamlit as st

from components.model_info import fetch_model_info, format_data_source, format_model_info


def humanize_age(updated_at: str | None) -> str:
    if not updated_at:
        return "never analyzed"
    dt = datetime.fromisoformat(updated_at)
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    if age < 60:
        return "just now"
    if age < 3600:
        return f"{int(age // 60)} min ago"
    if age < 86400:
        return f"{int(age // 3600)}h ago"
    return f"{int(age // 86400)}d ago"


def fetch_company(api_url: str, symbol: str) -> dict | None:
    try:
        response = httpx.get(f"{api_url}/company/{symbol}", timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        st.error(f"Could not fetch status: {exc}")
        return None
    return response.json()


def render_specialist_page(
    *,
    api_url: str,
    symbol: str,
    specialist: str,
    render_result: Callable[[dict], None],
    poll_seconds: int = 5,
    also_refresh: list[str] | None = None,
    status_slot=None,
    extra_refresh_body: dict | None = None,
) -> None:
    """`also_refresh`: other specialist(s) to trigger in the same "Analyze"
    click, with no UI of their own — e.g. `affo` alongside
    `financial_statements`: a separate, independently-cached specialist
    (its own TTL, its own slow SEC-filing extraction) without its own
    visible Refresh/Analyze control. One click starts both, and whichever
    finishes first renders first; if `also_refresh` specialists are still
    running after this page's own `specialist` is already "done", a small
    background poller keeps watching them and reruns the page once they
    land, so newly-available data (e.g. AFFO rows merged into the Income
    Statement table) appears without a manual refresh.

    `status_slot`: an `st.empty()` container the caller created near the
    TOP of the page, passed in so the "still computing" message renders
    there instead of wherever in the script this function happens to be
    called from — on a page with several sections below this call, that
    status would otherwise end up at the very bottom, visible only after
    scrolling past everything else. Optional and defaults to inline `st.*`
    calls (unchanged behavior) for callers that don't pass one.

    `extra_refresh_body`: extra fields merged into the `/refresh` POST body
    — e.g. `{"affo_iterations": 3}`, a page-specific control (how many
    filings to process in one AFFO run) that doesn't belong hardcoded into
    this shared component.
    """
    if not symbol:
        return
    also_refresh = also_refresh or []

    company = fetch_company(api_url, symbol)
    if company is None:
        return
    symbol_kind = company.get("symbol_kind")
    if symbol_kind in ("etf", "fund"):
        st.info(
            f"**{symbol}** is {'an ETF' if symbol_kind == 'etf' else 'a fund'} — this specialist "
            "isn't built for funds yet (assumes an operating company's own financial statements/"
            "earnings), so nothing runs for it."
        )
        return
    entry = company["specialists"][specialist]
    also_expired = any(company["specialists"][name]["is_expired"] for name in also_refresh)
    locked = company.get("is_refreshing", False)

    model_info = format_model_info(fetch_model_info(api_url).get(specialist))
    data_source = format_data_source(entry.get("result"))
    col1, col2 = st.columns([2, 1])
    col1.caption(
        f"Last updated: {humanize_age(entry['updated_at'])} · Model: {model_info}"
        + (f" · Data: {data_source}" if data_source else "")
    )
    refresh_checked = col2.checkbox(
        "Refresh", value=entry["is_expired"] or also_expired, key=f"{specialist}_refresh", disabled=locked
    )

    if st.button("Analyze", key=f"{specialist}_analyze", disabled=locked) and refresh_checked:
        start_refresh(
            api_url, symbol, {"specialists": [specialist, *also_refresh], **(extra_refresh_body or {})}
        )

    # A refresh for this symbol may be running from a DIFFERENT page (e.g.
    # this specialist's own status just sits at "done"/"never_run" while
    # another page's Analyze click is in flight) — poll for the lock to
    # clear so the Analyze button re-enables without a manual reload.
    if locked and entry["status"] not in ("pending", "running"):
        target = status_slot if status_slot is not None else st
        target.caption("A refresh is running for this symbol (started from another page) — waiting for it to finish.")
        poll_refresh_lock(api_url, symbol, poll_seconds, key=f"lock_{specialist}")

    if entry["status"] in ("pending", "running"):
        _poll_status(api_url, symbol, specialist, poll_seconds, status_slot)
    elif entry["status"] == "error":
        st.error(f"Analysis failed: {entry['error']}")
    elif entry["status"] == "done":
        render_result(entry["result"])
        _poll_background(api_url, symbol, also_refresh, poll_seconds, status_slot)
    else:
        st.caption("Not analyzed yet — check the box above and click Analyze.")


def start_refresh(api_url: str, symbol: str, body: dict) -> None:
    try:
        response = httpx.post(f"{api_url}/company/{symbol}/refresh", json=body, timeout=10)
    except httpx.HTTPError as exc:
        st.error(f"Could not start refresh: {exc}")
        return
    if response.status_code == 409:
        st.warning("A refresh for this symbol just started from another page — try again once it finishes.")
        return
    st.rerun()


def poll_refresh_lock(api_url: str, symbol: str, poll_seconds: int, key: str) -> None:
    @st.fragment(run_every=poll_seconds, key=key)
    def _fragment() -> None:
        company = fetch_company(api_url, symbol)
        if company is not None and not company.get("is_refreshing", False):
            st.rerun()

    _fragment()


def _poll_status(api_url: str, symbol: str, specialist: str, poll_seconds: int, status_slot=None) -> None:
    """Reruns only this fragment every `poll_seconds`, via Streamlit's own
    WebSocket protocol — NOT a raw `<meta http-equiv="refresh">` full
    browser reload, which navigates the browser to the current URL and, on
    a multipage app's sub-page path, breaks Streamlit's own relative
    internal asset paths and wipes `st.session_state`. `st.fragment` avoids
    a browser navigation entirely, so neither symptom can occur.
    """

    @st.fragment(run_every=poll_seconds, key=f"poll_{specialist}")
    def _fragment() -> None:
        company = fetch_company(api_url, symbol)
        if company is None:
            return
        entry = company["specialists"][specialist]
        target = status_slot if status_slot is not None else st
        if entry["status"] in ("pending", "running"):
            target.info(
                f"Status: {entry['status']} ({specialist}) — this section auto-refreshes every "
                f"{poll_seconds}s. Safe to navigate away."
            )
        else:
            # Done or error — break out of the fragment with a full rerun so
            # the page re-enters render_specialist_page and renders the
            # final result/error normally.
            st.rerun()

    _fragment()


def _poll_background(api_url: str, symbol: str, specialists: list[str], poll_seconds: int, status_slot=None) -> None:
    """Watches `specialists` (the `also_refresh` list) even though this
    page's own primary specialist already rendered above — lets a slow
    companion specialist (AFFO) keep computing after the fast one (Financial
    Statements) is already showing, and triggers a full rerun once it lands
    so the merged data appears without the user doing anything.

    Checked ONCE, outside any fragment, before deciding whether to mount
    the polling fragment at all: `status == "never_run"` (e.g. AFFO on a
    non-REIT symbol, or any symbol never refreshed this session) reads the
    same as "nothing pending" as a completed run would inside the fragment,
    so without this upfront check the fragment would rerun on every single
    tick forever instead of recognizing there was never anything to wait
    for. If nothing is pending right now, this is a genuine no-op — the
    fragment only gets created when there's something real to wait for.
    """
    if not specialists:
        return

    company = fetch_company(api_url, symbol)
    if company is None:
        return
    if not any(company["specialists"][s]["status"] in ("pending", "running") for s in specialists):
        return

    @st.fragment(run_every=poll_seconds, key=f"poll_bg_{'_'.join(specialists)}")
    def _fragment() -> None:
        inner_company = fetch_company(api_url, symbol)
        if inner_company is None:
            return
        pending = [s for s in specialists if inner_company["specialists"][s]["status"] in ("pending", "running")]
        if pending:
            target = status_slot if status_slot is not None else st
            target.caption(f"Still computing in the background: {', '.join(pending)} — this section updates automatically when ready.")
        else:
            # Done or error — full rerun so the page re-enters
            # render_specialist_page with fresh data (e.g. AFFO now merged
            # into the Income Statement/Capital Return tables). A fresh
            # script run naturally recreates status_slot empty next time,
            # so nothing extra needs clearing here.
            st.rerun()

    _fragment()
