import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.health_banner import render_specialist_health_warning
from components.model_info import fetch_model_info, format_data_source, format_model_info
from components.specialist_page import fetch_company, humanize_age, poll_refresh_lock, start_refresh
from components.symbol import symbol_input
from components.text import escape_dollars

# Specialists shown/refreshable from this overview. The remaining
# specialists in orchestration.py's SPECIALISTS each have their own
# dedicated page instead. Must match `_CROSS_SIGNAL_REQUIRED` in
# orchestration.py, or the cross-signal summary below can never fire.
# An ordered tuple, not a set — the loop below iterates this directly to
# control display order (independent of SPECIALISTS' dict order).
_VISIBLE_SPECIALISTS = (
    "financial_statements",
    "affo",
    "technical",
    "sentiment",
    "earnings_call",
    "valuation",
    "disruption",
    "earnings",
    "risk",
    "performance",
)

# Piggybacked silently onto every refresh (see _render_overview) for the
# Identity Card's price/market cap — has no row of its own in the form
# above, but still needs to be watched for "pending" so the polling
# fragment below doesn't stop before it's actually done.
_POLL_SPECIALISTS = _VISIBLE_SPECIALISTS + ("data_collector",)

st.set_page_config(page_title="Stock Analysis", layout="wide")
hide_skills_nudge()
st.title("Stock Analysis")
st.caption(
    "Fundamental Deep Dive, Technical Charts, and Sentiment & News specialists only, for now. "
    "Each specialist has its own dedicated page for full detail and its own freshness — this "
    "page just shows the overview and the cross-signal summary."
)

render_specialist_health_warning(API_URL)

symbol = symbol_input()

if not symbol:
    st.stop()


def _render_identity_card(symbol: str, company: dict) -> None:
    """Static company identity (cached once via orchestration.py::get_symbol_kind,
    same FMP profile call as the ETF/fund check) plus live price/market cap
    from the data_collector specialist, piggybacked on every refresh below.
    Renders nothing beyond a placeholder until the symbol has been analyzed
    at least once — same "nothing shows until refreshed" pattern as the
    rest of this page.
    """
    identity = company.get("identity")
    if not identity:
        st.caption("Identity card appears after the first analysis of this symbol.")
        return

    dc_result = (company["specialists"].get("data_collector") or {}).get("result") or {}
    risk_result = (company["specialists"].get("risk") or {}).get("result") or {}
    technical_result = (company["specialists"].get("technical") or {}).get("result") or {}

    name = identity.get("company_name") or symbol
    header = f"### {name} ({symbol})"
    price = dc_result.get("price")
    previous_close = dc_result.get("previous_close")
    if price is not None:
        change_str = ""
        if previous_close:
            change_pct = (price - previous_close) / previous_close * 100
            sign = "+" if change_pct >= 0 else ""
            change_str = f" ({sign}{change_pct:.2f}%)"
        header += f" — ${price:,.2f}{change_str}"
    st.markdown(header)

    meta_bits = [b for b in (identity.get("exchange"), identity.get("sector"), identity.get("industry")) if b]
    if meta_bits:
        st.caption(" · ".join(meta_bits))

    market_cap = dc_result.get("market_cap")
    if market_cap:
        st.caption(f"Market cap: ${market_cap:,.0f}")

    badge_col1, badge_col2, badge_col3 = st.columns(3)
    badge_col1.metric("Technical trend", technical_result.get("trend", "—"))
    badge_col2.metric("Risk level", risk_result.get("risk_level", "—"))
    badge_col3.metric("Solvency (Altman)", risk_result.get("altman_zone") or "—")

    description = identity.get("description")
    if description:
        with st.expander("Company description"):
            st.write(description)

    st.divider()


def _signal_matrix_rows(company: dict, is_reit: bool | None) -> list[dict]:
    """One row per visible specialist that has actually run — each with a
    single key metric and a short interpretation, so the whole analysis can
    be scanned at a glance instead of opening every specialist's own page.
    Never-run/error specialists are skipped rather than shown as empty rows
    (the "Specialists" form below already surfaces their status).
    """
    specialists = company["specialists"]
    rows: list[dict] = []

    def _add(label: str, metric: str, signal: str) -> None:
        rows.append({"Specialist": label, "Key metric": metric, "Signal": signal})

    fs = (specialists.get("financial_statements") or {})
    if fs.get("status") == "done":
        ce = (fs["result"].get("capital_efficiency") or {})
        roic, wacc, eva = ce.get("roic_pct"), ce.get("wacc_pct"), ce.get("eva")
        if roic is not None and wacc is not None:
            signal = "Value-creating" if (eva or 0) > 0 else "Value-destroying" if (eva or 0) < 0 else "—"
            _add("Financial Statements", f"ROIC {roic}% vs WACC {wacc}%", signal)

    affo = (specialists.get("affo") or {})
    if is_reit is True and affo.get("status") == "done":
        history = affo["result"].get("historical_data") or []
        if history:
            latest = history[-1]
            signal = "—"
            if len(history) >= 2 and latest.get("affo_per_share") is not None and history[-2].get("affo_per_share") is not None:
                signal = "Growing" if latest["affo_per_share"] > history[-2]["affo_per_share"] else "Shrinking"
            _add("AFFO", f"{latest.get('affo_per_share', '—')}/share", signal)

    technical = (specialists.get("technical") or {})
    if technical.get("status") == "done":
        r = technical["result"]
        _add("Technical", f"Last close ${r.get('last_close', '—')}", r.get("trend", "—").title())

    sentiment = (specialists.get("sentiment") or {})
    if sentiment.get("status") == "done":
        r = sentiment["result"]
        score = r.get("average_score")
        _add("Sentiment", f"Score {score:.2f}" if score is not None else "—", r.get("tone", "—").title())

    earnings_call = (specialists.get("earnings_call") or {})
    if earnings_call.get("status") == "done":
        r = earnings_call["result"]
        evasive = len(r.get("evasive_statements") or [])
        signal = f"{evasive} evasive answer{'s' if evasive != 1 else ''} flagged" if evasive else "None flagged"
        # management_tone is a full sentence, not a single-word label like
        # the other specialists' fields — shown as-is (truncated), not .title()'d.
        tone = r.get("management_tone") or "—"
        tone = tone if len(tone) <= 80 else tone[:77] + "..."
        _add("Earnings Call", tone, signal)

    valuation = (specialists.get("valuation") or {})
    if valuation.get("status") == "done":
        r = valuation["result"]
        fair_value = (r.get("dcf") or {}).get("fair_value_per_share")
        price = ((specialists.get("data_collector") or {}).get("result") or {}).get("price")
        if fair_value is not None and price:
            gap_pct = (fair_value - price) / price * 100
            metric = f"DCF ${fair_value:,.2f} vs price ${price:,.2f}"
            signal = f"{'Undervalued' if gap_pct > 0 else 'Overvalued'} {abs(gap_pct):.1f}%"
        else:
            metric = f"DCF ${fair_value:,.2f}" if fair_value is not None else "—"
            signal = "—"
        _add("Valuation", metric, signal)

    disruption = (specialists.get("disruption") or {})
    if disruption.get("status") == "done":
        r = disruption["result"]
        _add(
            "Disruption",
            r.get("disruption_posture", "—").title(),
            f"Risk score {r.get('disruption_risk_score', 0):.2f}",
        )

    earnings = (specialists.get("earnings") or {})
    if earnings.get("status") == "done":
        r = earnings["result"]
        surprise = r.get("latest_eps_surprise_pct")
        metric = f"{surprise:+.1f}% EPS surprise" if surprise is not None else "—"
        _add("Earnings", metric, r.get("trend", "—").title())

    risk = (specialists.get("risk") or {})
    if risk.get("status") == "done":
        r = risk["result"]
        _add("Risk", r.get("risk_level", "—").title(), (r.get("altman_zone") or "—").title())

    performance = (specialists.get("performance") or {})
    if performance.get("status") == "done":
        r = performance["result"]
        ret_1y, bench_1y = r.get("return_1y"), r.get("benchmark_return_1y")
        metric = f"{ret_1y:+.1f}% (1y)" if ret_1y is not None else "—"
        signal = "—"
        if ret_1y is not None and bench_1y is not None:
            signal = f"{'Outperforming' if ret_1y > bench_1y else 'Underperforming'} {r.get('benchmark_symbol', 'benchmark')}"
        _add("Performance", metric, signal)

    return rows


def _render_signal_matrix(company: dict, is_reit: bool | None) -> None:
    rows = _signal_matrix_rows(company, is_reit)
    if not rows:
        return
    st.subheader("Signal matrix")
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.divider()


def _render_overview(symbol: str) -> dict | None:
    company = fetch_company(API_URL, symbol)
    if company is None:
        return None

    symbol_kind = company.get("symbol_kind")
    if symbol_kind in ("etf", "fund"):
        st.info(
            f"**{symbol}** is {'an ETF' if symbol_kind == 'etf' else 'a fund'} — none of these "
            "specialists are built for funds yet (they all assume an operating company's own "
            "financial statements/earnings), so nothing runs for it."
        )
        return company

    # Known independently of whether AFFO itself has ever run (same source
    # Fundamental Deep Dive uses) — capital_return.py checks the company's
    # own FMP industry, so this works even on a symbol never analyzed here
    # before.
    fs_result = (company["specialists"].get("financial_statements") or {}).get("result") or {}
    is_reit = (fs_result.get("capital_return") or {}).get("is_reit")

    _render_identity_card(symbol, company)
    _render_signal_matrix(company, is_reit)

    model_info = fetch_model_info(API_URL)

    st.subheader("Cross-signal summary")
    orchestrator = company.get("orchestrator")
    if orchestrator and orchestrator.get("summary"):
        st.write(escape_dollars(orchestrator["summary"]))
        if orchestrator.get("contradictions"):
            st.subheader("Contradictions flagged")
            for c in orchestrator["contradictions"]:
                st.warning(
                    f"({', '.join(c['involved_agents'])}) " + escape_dollars(c["description"])
                )
        st.caption(f"Computed {humanize_age(orchestrator.get('updated_at'))}")
    else:
        st.caption(
            "No cross-signal summary yet — appears automatically once the specialists below are "
            "fresh (refresh any that are expired)."
        )

    st.divider()
    st.subheader("Specialists")
    st.caption(
        "Analyze always runs every specialist below together, so the cross-signal summary is "
        "computed once against a fully up-to-date set — not per specialist. To refresh just one, "
        "use that specialist's own dedicated page instead."
    )
    locked = company.get("is_refreshing", False)

    for name in _VISIBLE_SPECIALISTS:
        entry = company["specialists"].get(name)
        if entry is None:
            continue
        if name == "affo" and is_reit is not True:
            # Hidden unless a REIT is POSITIVELY confirmed — otherwise every
            # never-analyzed symbol would show it. A brand-new REIT still
            # gets AFFO run as part of "Analyze" below even with the row
            # hidden, since Analyze always sends every visible specialist.
            continue
        col1, col2 = st.columns([2, 4])
        col1.write(f"**{name.replace('_', ' ').title()}**")
        data_source = format_data_source(entry.get("result"))
        col2.caption(
            f"{entry['status']} — {humanize_age(entry['updated_at'])} · "
            f"Model: {format_model_info(model_info.get(name))}"
            + (f" · Data: {data_source}" if data_source else "")
        )

    # Orchestrator (cross-signal step) shown alongside the specialists —
    # informational only, never triggered directly by the user, only
    # automatically once every specialist above is fresh (see
    # orchestration.py::refresh_company). Its own "running" status is
    # otherwise invisible: it can keep computing for a while after every
    # specialist the user was watching already shows "done".
    orchestrator_status = company.get("orchestrator", {})
    col1, col2 = st.columns([2, 4])
    col1.write("**Orchestrator**")
    col2.caption(
        f"{orchestrator_status.get('status', 'never_run')} — "
        f"{humanize_age(orchestrator_status.get('updated_at'))} · "
        f"Model: {format_model_info(model_info.get('orchestrator'))}"
    )
    if orchestrator_status.get("status") == "error":
        st.error(f"Cross-signal synthesis failed: {orchestrator_status.get('error')}")

    with st.form("orch_specialists_form"):
        affo_iterations = st.select_slider(
            "AFFO history depth", options=[1, 2, 3], value=1, key="orch_affo_iterations",
            disabled=locked,
        )
        submitted = st.form_submit_button("Analyze", disabled=locked)

    if locked:
        st.caption("A refresh is already running for this symbol — waiting for it to finish.")
        poll_refresh_lock(API_URL, symbol, poll_seconds=5, key="lock_stock_analysis")

    if submitted:
        specialists_to_send = list(_VISIBLE_SPECIALISTS) + ["data_collector"]
        start_refresh(
            API_URL, symbol, {"specialists": specialists_to_send, "affo_iterations": affo_iterations}
        )

    return company


def _poll_while_pending(symbol: str, company: dict) -> None:
    """Checks ONCE, outside any fragment, whether anything is actually
    pending; only mounts the auto-refreshing fragment when there's
    something real to wait for, then does a full `st.rerun()` once nothing
    is pending so the page picks up the finished result. Same pattern as
    `components/specialist_page.py`'s polling helpers — avoids an
    unconditional `run_every` fragment rerunning (and flickering) forever
    even at rest.

    Takes `company` from the caller's own already-fetched snapshot rather
    than fetching again here — a separate fetch here could read a
    split-second-stale "nothing pending yet" state right after a refresh
    was triggered, skip mounting the fragment, and then never poll again
    until the user manually interacted with the page.
    """
    def _orchestrator_pending(c: dict) -> bool:
        return c.get("orchestrator", {}).get("status") in ("pending", "running")

    if not any(
        company["specialists"].get(name, {}).get("status") in ("pending", "running")
        for name in _POLL_SPECIALISTS
    ) and not _orchestrator_pending(company):
        return

    @st.fragment(run_every=5, key="stock_analysis_poll")
    def _fragment() -> None:
        inner = fetch_company(API_URL, symbol)
        if inner is None:
            return
        pending = [
            name
            for name in _POLL_SPECIALISTS
            if inner["specialists"].get(name, {}).get("status") in ("pending", "running")
        ]
        if _orchestrator_pending(inner):
            pending.append("orchestrator")
        # Rerunning only once `pending` is EMPTY would make every specialist
        # appear to finish at the same instant — a fast specialist (e.g.
        # Technical) would sit at "running" on screen for as long as the
        # slowest one takes, even though its own status already flipped to
        # "done" server-side. Rerunning on every tick instead means each
        # poll re-renders the current per-specialist state, so a finished
        # one shows as done immediately while the rest keep polling. The
        # outer guard above already ensures this fragment only exists while
        # something is genuinely pending, so this can't loop forever once
        # everything settles — the next full rerun just won't remount it.
        if pending:
            st.info(f"Still running: {', '.join(pending)} — this updates automatically when ready.")
        st.rerun()

    _fragment()


_company_snapshot = _render_overview(symbol)
if _company_snapshot is not None:
    _poll_while_pending(symbol, _company_snapshot)
