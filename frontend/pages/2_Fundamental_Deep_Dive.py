import streamlit as st

from components.chrome import hide_skills_nudge
from components.config import API_URL
from components.model_info import fetch_model_info, format_model_info
from components.specialist_page import fetch_company, humanize_age, render_specialist_page
from components.statement_table import render_simple_table, render_statement_table
from components.symbol import symbol_input
from components.text import escape_dollars

st.set_page_config(page_title="Fundamental Deep Dive", layout="wide")
hide_skills_nudge()
st.title("Fundamental Deep Dive")

symbol = symbol_input()

# Created here, at the top, so a "still computing" status message always
# shows immediately, instead of wherever in the script the background AFFO
# poll happens to fire (after Capital Efficiency/Capital Return/
# Segmentation) — invisible until scrolled past everything else otherwise.
status_slot = st.empty()


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _fiscal_year_from_column(col: dict) -> int | None:
    try:
        return int(col["label"].split()[-1])
    except (ValueError, IndexError):
        return None


def _insert_affo_income_rows(income_table: dict, affo_history: list[dict], is_reit: bool) -> dict:
    """Page-level merge — financial_statements.py stays specialist-agnostic;
    AFFO comes from the separate `affo` specialist, so the two are stitched
    together here, after both are already fetched. Only meaningful for the
    *annual* Income Statement — AFFO is extracted from the 10-K only
    (quarterly extraction from 10-Qs deliberately deferred), so inserting it
    into the quarterly table would misleadingly repeat one annual figure
    across all 4 quarters of that year.

    Gated on `is_reit`, NOT on `affo_history` being non-empty — a REIT
    should show the REIT-shaped row structure (blank AFFO rows) from the
    very first view, not only after AFFO has actually produced data; values
    simply come out `None` until then.
    """
    if not is_reit or not income_table.get("rows"):
        return income_table
    affo_by_year = {y["fiscal_year"]: y for y in affo_history}
    columns = income_table["fiscal_years"]

    affo_values = []
    affo_ps_values = []
    for col in columns:
        y = affo_by_year.get(_fiscal_year_from_column(col))
        # AFFO is extracted as reported in the filing — SEC filings state
        # these figures in thousands, so *1000 converts to raw dollars
        # matching this table's "millions" convention for every other
        # dollar row. Not guaranteed universal — if a company instead
        # reports in millions, this would show 1000x too high (no
        # per-filing unit detection yet).
        affo_values.append(y["affo"] * 1000 if y and y.get("affo") is not None else None)
        affo_ps_values.append(y["affo_per_share"] if y else None)

    rows = list(income_table["rows"])
    idx = next((i for i, r in enumerate(rows) if r["label"] == "EPS Diluted"), None)
    if idx is None:
        return income_table
    affo_row = {
        "label": "AFFO",
        "is_bold": False,
        "is_subheader": True,
        "indent": 0,
        "format_type": "millions",
        "tooltip": "REIT-only. Adjusted Funds From Operations, extracted from the company's own 10-K "
        "reconciliation table (separate `affo` specialist) — converted from the filing's stated "
        "thousands to this table's millions convention.",
        "values": affo_values,
    }
    affo_ps_row = {
        "label": "AFFO/Share",
        "is_bold": True,
        "is_subheader": False,
        "indent": 0,
        "format_type": "raw",
        "tooltip": "REIT-only. AFFO / diluted weighted-average shares, as reported by the company.",
        "values": affo_ps_values,
    }
    rows[idx + 1 : idx + 1] = [affo_row, affo_ps_row]
    return {**income_table, "rows": rows}


def _apply_affo_payout_ratio(capital_return: dict, affo_history: list[dict], is_reit: bool) -> dict:
    """Replaces the Payout Ratio (EPS) row with Payout Ratio (AFFO) for
    REITs — EPS-based payout is always None for REITs anyway (EPS is
    dominated by real-estate depreciation), this fills that slot with the
    metric REIT investors actually use.

    Gated on `is_reit` alone, NOT also on `affo_history` — the label should
    already read "Payout Ratio (AFFO)" for a REIT even before AFFO has ever
    run; values just come out `None` until then, like every other
    not-yet-available row on this page.
    """
    if not is_reit:
        return capital_return
    affo_by_year = {y["fiscal_year"]: y for y in affo_history}
    columns = capital_return["fiscal_years"]
    rows = list(capital_return["rows"])
    dps_row = next((r for r in rows if r["label"] == "Dividends per Share (FY)"), None)
    idx = next((i for i, r in enumerate(rows) if r["label"] == "Payout Ratio (EPS)"), None)
    if idx is None or dps_row is None:
        return capital_return

    payout_affo_values = []
    for i, col in enumerate(columns):
        y = affo_by_year.get(_fiscal_year_from_column(col))
        dps = dps_row["values"][i] if i < len(dps_row["values"]) else None
        payout_affo_values.append(_safe_div(dps, y["affo_per_share"]) if y else None)

    rows[idx] = {
        **rows[idx],
        "label": "Payout Ratio (AFFO)",
        "tooltip": "Dividends per Share / AFFO per Share — the standard REIT payout measure "
        "(replaces the EPS-based ratio, which isn't meaningful for REITs).",
        "values": payout_affo_values,
    }
    return {**capital_return, "rows": rows}


_DUPONT_TOOLTIPS = {
    "Net Profit Margin": "Net Income / Revenue — operating efficiency: how much net profit remains from each dollar of revenue.",
    "× Tax Burden": "Net Income / EBT — share of profit kept after taxes (1 − effective tax rate).",
    "× Interest Burden": "EBT / EBIT — share of operating profit consumed by interest expense; closer to 1 means less cost from debt.",
    "× Operating Margin": "EBIT / Revenue — core operating profitability, before financing and taxes.",
    "× Asset Turnover": "Revenue / Total Assets — how efficiently assets are used to generate revenue.",
    "× Financial Leverage": "Total Assets / Shareholders' Equity (equity multiplier) — degree of indebtedness: assets controlled per dollar of equity.",
    "= ROE": "Net Income / Shareholders' Equity — the product of the factors above.",
}


def _render_financial_statements(report: dict) -> None:
    st.caption(
        f"View: **{report['view'].title()}** (auto-detected from sector) — "
        f"latest annual report {report.get('latest_annual_report_date') or 'n/a'}, "
        f"latest quarterly report {report.get('latest_quarterly_report_date') or 'n/a'}"
    )

    period_choice = st.radio("Period", ["Annual", "Quarterly"], horizontal=True, key="fs_period")
    key_prefix = "annual" if period_choice == "Annual" else "quarter"

    # AFFO is a separate specialist (own TTL, own SEC-filing extraction) —
    # triggered together with this one (`also_refresh=["affo"]` below) but
    # fetched here on its own, since render_specialist_page only hands this
    # callback its own specialist's result, not others'.
    # Gate on `result` being present, NOT `status == "done"` — a running
    # refresh flips status to "running" while this page re-renders, and
    # orchestration.py::run_specialist preserves `result` across that
    # transition, so stale-but-real data should still show rather than
    # disappearing until the new run finishes.
    affo_company = fetch_company(API_URL, symbol)
    affo_entry = (affo_company or {}).get("specialists", {}).get("affo") if affo_company else None
    affo_history = (affo_entry.get("result") or {}).get("historical_data") or [] if affo_entry else []

    # REIT status is known independently of the AFFO specialist
    # (capital_return.py checks the company's own industry via FMP profile,
    # same as affo_analyst.py does) — so the REIT-shaped layout (AFFO/
    # AFFO-Share rows, "Payout Ratio (AFFO)" label) renders from the very
    # first view, not only once affo_history has data.
    is_reit = report.get("capital_return", {}).get("is_reit", False)

    income_table = report[f"income_{key_prefix}"]
    if key_prefix == "annual":
        income_table = _insert_affo_income_rows(income_table, affo_history, is_reit)
    capital_return_table = _apply_affo_payout_ratio(report.get("capital_return", {}), affo_history, is_reit)

    tab_income, tab_balance, tab_cash = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow"])
    with tab_income:
        render_statement_table(income_table, key=f"fs_income_{key_prefix}")
    with tab_balance:
        render_statement_table(report[f"balance_{key_prefix}"], key=f"fs_balance_{key_prefix}")
    with tab_cash:
        render_statement_table(report[f"cash_{key_prefix}"], key=f"fs_cash_{key_prefix}")

    st.subheader("Capital Efficiency")
    st.caption("All figures based on the latest reported annual period (not TTM).")
    ce = report.get("capital_efficiency", {})

    with st.container(border=True):
        st.markdown("**Returns**")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("ROE", f"{ce['roe_pct']}%" if ce.get("roe_pct") is not None else None)
        col2.metric("ROCE", f"{ce['roce_pct']}%" if ce.get("roce_pct") is not None else None)
        col3.metric("ROIC", f"{ce['roic_pct']}%" if ce.get("roic_pct") is not None else "n/a (bank/REIT)")
        col4.metric("RORE (5y)", f"{ce['rore_pct']}%" if ce.get("rore_pct") is not None else None)

        with st.expander("What each factor measures"):
            st.markdown(
                "- **ROE** (Net Income / Shareholders' Equity) — overall profitability "
                "delivered to shareholders per dollar of equity they've invested.\n"
                "- **ROCE** (EBIT / Capital Employed, where Capital Employed = Total "
                "Assets − Current Liabilities) — profitability relative to all "
                "long-term capital deployed in the business, independent of how "
                "much of it is debt vs. equity.\n"
                "- **ROIC** (NOPAT / Invested Capital, where Invested Capital = "
                "Total Debt + Shareholders' Equity − Cash & Short-Term Investments) "
                "— after-tax operating return on the capital actually invested in "
                "the business; the number to compare against WACC below to judge "
                "value creation. Hidden for banks/REITs — interest income/expense "
                "and asset-heavy, debt-financed structures make the NOPAT/Invested "
                "Capital framework not meaningful for them.\n"
                "- **RORE (5y)** ((latest Diluted EPS − Diluted EPS 5 years ago) / "
                "(sum of Diluted EPS over the last 5 years − sum of Dividends/Share "
                "over the same 5 years)) — how effectively the company turns the "
                "profit it keeps after dividends into further EPS growth."
            )

    with st.container(border=True):
        st.markdown("**Cost of Capital & Value Creation**")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("WACC", f"{ce['wacc_pct']}%" if ce.get("wacc_pct") is not None else None)
        col2.metric("Cost of Equity", f"{ce['cost_of_equity_pct']}%" if ce.get("cost_of_equity_pct") is not None else None)
        col3.metric(
            "Cost of Debt (after-tax)",
            f"{ce['cost_of_debt_after_tax_pct']}%" if ce.get("cost_of_debt_after_tax_pct") is not None else None,
        )
        col4.metric("EVA", f"{ce['eva']:,.0f}" if ce.get("eva") is not None else None)

        with st.expander("What each factor measures"):
            st.markdown(
                "- **WACC** (Weighted Average Cost of Capital) — the blended "
                "return a company's investors (equity + debt) require, weighted "
                "by market value; the hurdle rate returns need to clear to create "
                "value. Computed via CAPM.\n"
                "- **Cost of Equity** (risk-free rate + beta × equity risk "
                "premium, CAPM) — the return shareholders require given the "
                "stock's risk relative to the market.\n"
                "- **Cost of Debt (after-tax)** — the effective interest rate the "
                "company pays on its debt, net of the tax shield from deductible "
                "interest expense.\n"
                "- **EVA** (Economic Value Added = NOPAT − Invested Capital × "
                "WACC) — dollar profit generated above and beyond what's needed "
                "to cover the cost of all capital used. Positive means the "
                "company earns more than its cost of capital (value creation); "
                "negative means it's destroying value even while profitable on "
                "paper — this is the same comparison as ROIC vs. WACC above, "
                "expressed in dollars instead of a percentage spread."
            )

    with st.container(border=True):
        st.markdown("**DuPont Decomposition of ROE**")
        st.caption("Hover a row label for its formula and what it measures.")
        d3 = ce.get("dupont_3factor", {})
        d5 = ce.get("dupont_5factor", {})
        roe_display = f"{ce['roe_pct']}%" if ce.get("roe_pct") is not None else "—"

        def _pct(v: float | None) -> str:
            return f"{v}%" if v is not None else "—"

        def _num(v: float | None) -> str:
            return f"{v}" if v is not None else "—"

        dupont_rows = [
            {
                "label": "Net Profit Margin",
                "is_bold": False,
                "values": [_pct(d3.get("net_margin_pct")), ""],
            },
            {
                "label": "× Tax Burden",
                "is_bold": False,
                "values": ["", _num(d5.get("tax_burden"))],
            },
            {
                "label": "× Interest Burden",
                "is_bold": False,
                "values": ["", _num(d5.get("interest_burden"))],
            },
            {
                "label": "× Operating Margin",
                "is_bold": False,
                "values": ["", _pct(d5.get("operating_margin_pct"))],
            },
            {
                "label": "× Asset Turnover",
                "is_bold": False,
                "values": [_num(d3.get("asset_turnover")), _num(d5.get("asset_turnover"))],
            },
            {
                "label": "× Financial Leverage",
                "is_bold": False,
                "values": [_num(d3.get("financial_leverage")), _num(d5.get("financial_leverage"))],
            },
            {
                "label": "= ROE",
                "is_bold": True,
                "values": [roe_display, roe_display],
            },
        ]
        for row in dupont_rows:
            row["tooltip"] = _DUPONT_TOOLTIPS[row["label"]]

        render_simple_table(["3-factor", "5-factor"], dupont_rows, key="fs_dupont")

        with st.expander("What each factor measures"):
            st.markdown(
                "- **Net Profit Margin** (Net Income / Revenue) — operating "
                "efficiency: how much net profit remains from each dollar of "
                "revenue.\n"
                "- **Tax Burden** (Net Income / EBT) — share of profit kept after "
                "taxes (1 − effective tax rate).\n"
                "- **Interest Burden** (EBT / EBIT) — share of operating profit "
                "consumed by interest expense; the closer to 1, the less debt is "
                "costing the company.\n"
                "- **Operating Margin** (EBIT / Revenue) — core operating "
                "profitability, before financing and taxes.\n"
                "- **Asset Turnover** (Revenue / Total Assets) — how efficiently "
                "assets are used to generate revenue.\n"
                "- **Financial Leverage** (Total Assets / Shareholders' Equity, "
                "equity multiplier) — degree of indebtedness: how many dollars of "
                "assets are controlled for each dollar of shareholders' equity.\n\n"
                "A rising ROE can come from a healthy source (higher margins, "
                "faster asset turnover) or a risky one (leverage inflated by "
                "aggressive borrowing or heavy buybacks) — the 5-factor split "
                "isolates financing and tax effects from core operating "
                "performance, making it possible to tell which one is driving the "
                "change."
            )

    st.subheader("Capital Return Policy")
    if capital_return_table.get("is_reit") and not affo_history:
        st.caption(
            "REIT — Payout Ratio (AFFO) will fill in once the AFFO specialist finishes (it runs "
            "automatically alongside this section, just slower — SEC filing download + one LLM call)."
        )
    render_statement_table(capital_return_table, key="fs_capital_return", max_height=350)

    with st.expander("What each factor measures"):
        st.markdown(
            "- **Dividends per Share (FY)** — sum of `adjDividend` for every dividend whose "
            "*declaration* date falls in this fiscal year, not calendar year (fiscal years don't "
            "align to the calendar for most companies).\n"
            "- **Dividend Growth (FY)** — year-over-year change in Dividends per Share.\n"
            "- **Payout Ratio (EPS)** — Dividends per Share / Diluted EPS: how much of accounting "
            "earnings gets paid out as dividends. Replaced by Payout Ratio (AFFO) for REITs, where "
            "EPS is a poor profitability measure (depreciation on real estate dominates it).\n"
            "- **Payout Ratio (FCF)** — Dividends per Share / Free Cash Flow per Share: how much of "
            "actual cash generated gets paid out — a sturdier measure than the EPS version, since it "
            "isn't distorted by non-cash accounting items.\n"
            "- **Diluted Shares Outstanding** — context row, same figure as the Income Statement.\n"
            "- **Share Count Growth (YoY)** — year-over-year change in diluted share count. "
            "Negative means the company retired more shares via buybacks than it issued (e.g. via "
            "stock-based compensation vesting); positive means dilution won that year.\n"
            "- **Buybacks** — cash spent on share repurchases.\n"
            "- **Stock-Based Compensation** — non-cash SBC expense, the dilution pressure buybacks "
            "are working against.\n\n"
            "FMP has no share-count split for \"shares retired via buyback\" vs. \"shares issued via "
            "SBC vesting\" — only dollar amounts for each. Buybacks and Stock-Based Compensation are "
            "the two dollar-denominated drivers behind the Share Count Growth row above them, not an "
            "exact reconciliation of it — read them together to judge the qualitative direction, not "
            "as a precise breakdown."
        )

    st.subheader("Segmentation")
    st.caption(
        "Revenue breakdown by product/business line and by geographic market, last 8 fiscal years. "
        "Years marked * don't reconcile to actual total revenue — see caveats below each table."
    )
    tab_product, tab_geo = st.tabs(["By Product / Business Line", "By Geography"])
    for tab, seg_key, seg_label in (
        (tab_product, "product_segmentation", "product"),
        (tab_geo, "geographic_segmentation", "geographic"),
    ):
        with tab:
            seg = report.get(seg_key, {})
            if not seg.get("has_data"):
                st.caption("No segmentation data available from FMP for this symbol.")
                continue
            render_statement_table(seg, key=f"fs_{seg_label}_segmentation", max_height=350)
            if seg.get("unreliable_years"):
                st.warning(
                    escape_dollars(
                        "Doesn't reconcile to actual revenue: "
                        + "; ".join(f"{u['fiscal_year']} ({u['reason']})" for u in seg["unreliable_years"])
                    )
                )

    st.write("**Confidence:**", report.get("confidence"))
    if report.get("caveats"):
        st.warning(escape_dollars("Caveats: " + "; ".join(report["caveats"])))


st.header("Standardized Financial Statements")

# Fetched early, before the slider, so the AFFO iterations control can be
# hidden outright for a confirmed non-REIT rather than rendering
# unconditionally with only its label hinting it's a no-op there.
_precheck_company = fetch_company(API_URL, symbol) if symbol else None
_is_reit_precheck = (
    ((_precheck_company or {}).get("specialists", {}).get("financial_statements") or {}).get("result") or {}
).get("capital_return", {}).get("is_reit")

affo_iterations = 1
_symbol_kind_precheck = (_precheck_company or {}).get("symbol_kind")
if _symbol_kind_precheck not in ("etf", "fund") and _is_reit_precheck is not False:
    affo_iterations = st.select_slider(
        "AFFO history depth per Analyze (REITs only)",
        options=[1, 2, 3],
        value=1,
        help="Each 10-K only covers ~2-3 fiscal years of AFFO history. Instead of clicking Analyze "
        "several times, pick how many filings to walk through in this one click — each iteration "
        "either picks up a newly-available year or reaches one filing further into the past. No "
        "effect for non-REITs (AFFO is a no-op for them either way).",
    )
    # AFFO has no visible row of its own on this page (it's triggered
    # silently via `also_refresh` below and its data merged into the
    # tables above) — this is the only place its own status/model would
    # otherwise be shown at all.
    _affo_entry_precheck = (_precheck_company or {}).get("specialists", {}).get("affo") or {}
    st.caption(
        f"AFFO: {_affo_entry_precheck.get('status', 'never_run')} — "
        f"{humanize_age(_affo_entry_precheck.get('updated_at'))} · "
        f"Model: {format_model_info(fetch_model_info(API_URL).get('affo'))}"
    )
render_specialist_page(
    api_url=API_URL,
    symbol=symbol,
    specialist="financial_statements",
    render_result=_render_financial_statements,
    also_refresh=["affo"],
    status_slot=status_slot,
    extra_refresh_body={"affo_iterations": affo_iterations},
)
