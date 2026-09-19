"""Capital Return Policy: dividend history bucketed by *fiscal* year (not
calendar year — a dividend's declaration date is matched against the
company's own fiscal-year-end dates, since fiscal years don't align to
calendar years for many companies), Payout Ratio from EPS and FCF/share,
and diluted share count context (for the buybacks-vs-dilution picture).

AFFO-based payout ratio for REITs deliberately NOT built here — FMP has no
dedicated fields for the pieces that actually move the number (maintenance
vs. growth CapEx split, gains on property sales, straight-line rent
adjustments), so a formula-based AFFO from FMP's raw statement lines would
be a confident-looking approximation with real error, not a
simplification. The accurate path is extracting the company's own reported
AFFO reconciliation from its 10-K, handled as its own separate specialist
(see `agents/affo_analyst.py`) and merged in at the page level. Payout
ratio is `None` for REITs until then, with an explicit caveat, rather than
a plausible-looking wrong number.
"""

import asyncio

from agentic.data.fmp_client import fmp_get
from agentic.tools.financial_statements import safe_div
from agentic.tools.company_profile import get_company_profile

_DIVIDEND_LIMIT = 100  # FMP's dividends endpoint isn't period-limited like statements; fetch a generous flat count


def _fiscal_year_buckets(annual_periods: list[dict]) -> list[dict]:
    """One bucket per fiscal year, `(prior year-end, this year-end]` — a
    dividend's declaration date falls in the fiscal year whose end date is
    the first one on/after it.
    """
    periods = sorted(annual_periods, key=lambda p: p["date"])
    buckets = []
    prev_end = None
    for p in periods:
        buckets.append(
            {
                "fiscal_year": p.get("fiscalYear") or p["date"][:4],
                "date": p["date"],
                "start": prev_end,
                "end": p["date"],
            }
        )
        prev_end = p["date"]
    return buckets


def _bucket_for_date(date_str: str, buckets: list[dict]) -> str | None:
    for b in buckets:
        if (b["start"] is None or date_str > b["start"]) and date_str <= b["end"]:
            return b["fiscal_year"]
    return None


async def get_capital_return_policy(symbol: str, years: int = 15) -> dict:
    # Fetch one extra fiscal year beyond what's displayed, purely to give the
    # first *displayed* bucket a real lower boundary. Without it, bucket 0
    # has no prior year-end to compare against and silently absorbs every
    # dividend ever declared before the fetch window, inflating that year's
    # total with decades of unrelated history.
    fetch_years = years + 1
    profile, income_periods, cash_periods, dividends = await asyncio.gather(
        get_company_profile(symbol),
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, period="annual", limit=fetch_years),
        asyncio.to_thread(fmp_get, "cash-flow-statement", symbol=symbol, period="annual", limit=fetch_years),
        asyncio.to_thread(fmp_get, "dividends", symbol=symbol, limit=_DIVIDEND_LIMIT),
    )
    income_periods = sorted(income_periods, key=lambda p: p["date"])
    cash_periods = sorted(cash_periods, key=lambda p: p["date"])
    all_buckets = _fiscal_year_buckets(income_periods)
    buckets = all_buckets[-years:]
    is_reit = (profile.get("industry") or "").startswith("REIT")

    dividends_by_fy: dict[str, float] = {}
    for d in dividends:
        decl = d.get("declarationDate")
        adj = d.get("adjDividend")
        if not decl or adj is None:
            continue
        fy = _bucket_for_date(decl, all_buckets)
        if fy is None:
            continue
        dividends_by_fy[fy] = dividends_by_fy.get(fy, 0.0) + adj

    shares_by_date = {p["date"]: p.get("weightedAverageShsOutDil") for p in income_periods}
    eps_by_date = {p["date"]: p.get("epsDiluted") for p in income_periods}
    fcf_per_share_by_date = {
        p["date"]: safe_div(p.get("freeCashFlow"), shares_by_date.get(p["date"])) for p in cash_periods
    }

    fiscal_years = [{"label": f"FY {b['fiscal_year']}", "date": b["date"], "is_estimate": False} for b in buckets]

    dps_values = [dividends_by_fy.get(b["fiscal_year"]) for b in buckets]

    def _growth_series(values: list[float | None]) -> list[float | None]:
        out: list[float | None] = [None]
        for i in range(1, len(values)):
            out.append(safe_div(None if values[i] is None or values[i - 1] is None else values[i] - values[i - 1], values[i - 1]))
        return out

    payout_eps_values = [
        None if is_reit else safe_div(dps_values[i], eps_by_date.get(b["date"]))
        for i, b in enumerate(buckets)
    ]
    payout_fcf_values = [
        safe_div(dps_values[i], fcf_per_share_by_date.get(b["date"])) for i, b in enumerate(buckets)
    ]
    shares_diluted_values = [shares_by_date.get(b["date"]) for b in buckets]
    shares_growth_values = _growth_series(shares_diluted_values)

    # FMP has no share-count split for "shares retired via buyback" vs.
    # "shares issued via SBC vesting" — only dollar amounts, and
    # `commonStockIssued` is null for ordinary companies (issuance rolls
    # into `commonStockRepurchased` as one net figure), so there's no
    # cleaner split available to compute here. These two rows next to the
    # share-count trend let the reader judge the qualitative dynamic
    # (buybacks outpacing dilution vs. the reverse) themselves.
    cash_by_date = {p["date"]: p for p in cash_periods}

    def _repurchased(date: str) -> float | None:
        v = cash_by_date.get(date, {}).get("commonStockRepurchased")
        return None if v is None else -v

    buybacks_values = [_repurchased(b["date"]) for b in buckets]
    sbc_values = [cash_by_date.get(b["date"], {}).get("stockBasedCompensation") for b in buckets]

    rows = [
        {
            "label": "Dividends per Share (FY)",
            "is_bold": True,
            "is_subheader": False,
            "indent": 0,
            "format_type": "raw",
            "tooltip": "Sum of adjDividend for dividends whose declaration date falls in this fiscal year (not calendar year).",
            "values": dps_values,
        },
        {
            "label": "Dividend Growth (FY)",
            "is_bold": False,
            "is_subheader": False,
            "indent": 0,
            "format_type": "percentage",
            "tooltip": None,
            "values": _growth_series(dps_values),
        },
        {
            "label": "Payout Ratio (EPS)",
            "is_bold": False,
            "is_subheader": False,
            "indent": 0,
            "format_type": "percentage",
            "tooltip": "Dividends per Share / Diluted EPS. Not meaningful for REITs (depreciation dominates EPS) — the page "
            "replaces this row with Payout Ratio (AFFO) for REITs once AFFO data is available; see Financial Statements' "
            "Income Statement tab for the AFFO figures themselves."
            if is_reit
            else "Dividends per Share / Diluted EPS.",
            "values": payout_eps_values,
        },
        {
            "label": "Payout Ratio (FCF)",
            "is_bold": False,
            "is_subheader": False,
            "indent": 0,
            "format_type": "percentage",
            "tooltip": "Dividends per Share / Free Cash Flow per Share.",
            "values": payout_fcf_values,
        },
        {
            "label": "Diluted Shares Outstanding",
            "is_bold": True,
            "is_subheader": True,
            "indent": 0,
            "format_type": "millions",
            "tooltip": "Context row — same figure as the Income Statement.",
            "values": shares_diluted_values,
        },
        {
            "label": "Share Count Growth (YoY)",
            "is_bold": False,
            "is_subheader": False,
            "indent": 1,
            "format_type": "percentage",
            "tooltip": "Negative means the diluted share count fell — buybacks outpaced dilution that year; positive means dilution won.",
            "values": shares_growth_values,
        },
        {
            "label": "Buybacks",
            "is_bold": False,
            "is_subheader": False,
            "indent": 1,
            "format_type": "millions",
            "tooltip": "Cash spent on share repurchases (commonStockRepurchased). FMP has no share-count split for buybacks vs. SBC-driven "
            "issuance — this and Stock-Based Compensation below are the two dollar-denominated drivers behind the share count trend above, "
            "not an exact reconciliation of it.",
            "values": buybacks_values,
        },
        {
            "label": "Stock-Based Compensation",
            "is_bold": False,
            "is_subheader": False,
            "indent": 1,
            "format_type": "millions",
            "tooltip": "Non-cash SBC expense — the dilution pressure buybacks are working against.",
            "values": sbc_values,
        },
    ]

    return {
        "fiscal_years": fiscal_years,
        "rows": rows,
        "is_reit": is_reit,
    }
