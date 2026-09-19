"""AFFO extraction — single-LLM-call tier (same category as valuation/
disruption/sentiment): one tool-free completion over pre-fetched
text, no tool-calling loop. REIT-only; every other symbol short-circuits
before any SEC download or LLM call happens, keeping refresh cheap for the
99% of symbols this doesn't apply to.

Confidence/caveats are computed here in Python from what was actually
extracted (matching this project's consistent rule: never let the LLM
self-report its own confidence) — not asked from the model.
"""

import asyncio

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agentic.data.base import DataProvider
from agentic.data.fmp_client import fmp_get
from agentic.db import repository
from agentic.db.session import SessionLocal
from agentic.llm import get_model
from agentic.schemas.affo import AFFOReport, AFFOYearData
from agentic.tools.affo_extraction import get_affo_reconciliation_text
from agentic.tools.company_profile import get_company_profile

# Matches financial_statements.py's own `_FALLBACK_LIMIT` — the annual
# Income Statement table AFFO gets stitched into never shows more than 15
# fiscal-year columns, so walking further back into SEC history than that
# would burn SEC downloads + an LLM call per year for data that could never
# actually be displayed anywhere on the page.
_MAX_HISTORY_YEARS = 15


class _AFFOExtraction(BaseModel):
    metric_name_used_by_company: str = Field(
        description="The term the company itself uses for this metric — AFFO, FAD, CAD, etc."
    )
    historical_data: list[AFFOYearData] = Field(default_factory=list)


_affo_extraction_agent = Agent(
    get_model("affo"),
    output_type=_AFFOExtraction,
    retries={"output": 3},
    system_prompt=(
        "You are a financial-accounting analyst specializing in SEC filings (10-K/10-Q). "
        "Extract the historical annual FFO (Funds From Operations) and AFFO (Adjusted Funds "
        "From Operations) reconciliation from the table provided, given as pipe-separated rows "
        "extracted directly from the filing's HTML.\n\n"
        "STRICT RULES:\n"
        "1. Extract values per fiscal year (FY) for: net income, FFO, FFO per share (diluted), "
        "AFFO, AFFO per share (diluted), and diluted weighted-average shares.\n"
        "2. If a value is missing from the table, use null. Never invent or interpolate a value.\n"
        "3. Companies use different terms for this metric — not just \"AFFO\". Treat \"FFO as "
        "Adjusted\", \"Core FFO\", \"Normalized FFO\", CAD (Cash Available for Distribution), and "
        "FAD (Funds Available for Distribution) as equivalent to AFFO — map whichever one the "
        "company reports into the `affo`/`affo_per_share` fields, and record the actual term used "
        "in `metric_name_used_by_company`.\n"
        "4. The input may contain more than one table (separated by '---'), e.g. one with dollar "
        "amounts and a separate one with per-share figures for the same fiscal years — combine "
        "them into one row per fiscal year rather than treating them as different years.\n"
        "5. Respond ONLY with the required structured output."
    ),
)


def _load_previous_state(symbol: str) -> tuple[list[AFFOYearData], list[str]]:
    """Reads this specialist's OWN previously-stored result for `symbol` —
    a deliberate exception to every other specialist's "pure function over
    external market-data APIs only" pattern. A single 10-K only ever covers
    ~2-3 fiscal years of AFFO reconciliation, while the Income Statement
    table this feeds into shows up to 15 years. Instead of re-fetching the
    same latest 10-K every refresh, each run either picks up a genuinely
    new filing (a new fiscal year appeared) or walks backward to the filing
    just before the earliest one already processed — so repeated refreshes
    make real progress instead of reconfirming the same 2-3 years forever.
    Returns `(historical_data, processed_filing_dates, years_per_table)`.
    """
    db = SessionLocal()
    try:
        row = repository.get_company_analysis(db, symbol)
        if row is None:
            return [], [], None
        entry = (row.specialists or {}).get("affo")
        # Deliberately NOT gated on status == "done": this is read from
        # inside a run that `run_specialist` has already flipped to
        # "running" for this exact specialist (see orchestration.py) — the
        # prior `result` is still what's there, just no longer under a
        # "done" status.
        if not entry or not entry.get("result"):
            return [], [], None
        result = entry.get("result") or {}
        raw_history = result.get("historical_data") or []
        return (
            [AFFOYearData(**item) for item in raw_history],
            list(result.get("processed_filing_dates") or []),
            result.get("years_per_table"),
        )
    finally:
        db.close()


def _merge_history(previous: list[AFFOYearData], fresh: list[AFFOYearData]) -> list[AFFOYearData]:
    by_year: dict[int, AFFOYearData] = {y.fiscal_year: y for y in previous}
    for y in fresh:
        by_year[y.fiscal_year] = y  # a fresh extraction for a year overwrites the stored one
    return sorted(by_year.values(), key=lambda y: y.fiscal_year)


async def analyze_affo(provider: DataProvider, symbol: str, iterations: int = 1) -> AFFOReport:
    """`iterations` (1-3, clamped): how many 10-Ks to process in this single
    run — one click, the loop happens here, not via separate refresh
    requests that would also needlessly re-trigger `financial_statements`/
    FMP each time. Each iteration either picks up newly-available fiscal
    year(s) (if the latest
    10-K isn't reflected in stored history yet) or jumps back TWO filings at
    once, skipping the one directly in between (if already caught up) — see
    `_load_previous_state` and the skip-ahead comment below for why: every
    10-K's 2-year comparative table structurally overlaps the immediately
    preceding filing's by exactly one year, so the in-between filing would
    only ever add 1 new fiscal year; skipping straight to the one after it
    reliably nets 2 new years per iteration instead.
    """
    iterations = max(1, min(3, iterations))

    profile = await get_company_profile(symbol)
    is_reit = (profile.get("industry") or "").startswith("REIT")

    # limit=20, not 1: also used below to cross-check every extracted year's
    # `net_income` against FMP's own independently-reported figure for that
    # fiscal year — the strongest anchor available for catching a
    # mislabeled/swapped year, since unlike AFFO/share it's a field FMP
    # already reports per-year with no LLM involved.
    income = await asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, period="annual", limit=20)
    latest_annual_report_date = income[0]["date"] if income else None
    # FMP returns fiscalYear as a string (e.g. "2025") — coerce to int
    # before comparing/subtracting against AFFOYearData.fiscal_year, an int.
    latest_fiscal_year = int(income[0]["fiscalYear"]) if income and income[0].get("fiscalYear") is not None else None
    fmp_net_income_by_fy = {
        int(r["fiscalYear"]): r["netIncome"]
        for r in income
        if r.get("fiscalYear") is not None and r.get("netIncome") is not None
    }

    if not is_reit:
        return AFFOReport(
            symbol=symbol,
            is_reit=False,
            latest_annual_report_date=latest_annual_report_date,
            data_source="fmp",  # short-circuits before any SEC download happens
            confidence=1.0,
            caveats=[],
            historical_data=[],
            summary=f"{symbol} is not a REIT — AFFO doesn't apply.",
        )

    history, filing_dates, years_per_table = await asyncio.to_thread(_load_previous_state, symbol)
    metric_name: str | None = None
    run_caveats: list[str] = []
    iterations_done = 0

    for i in range(iterations):
        skip_candidate: tuple[str, str] | None = None
        stored_years = {y.fiscal_year for y in history}
        if latest_fiscal_year is not None and latest_fiscal_year not in stored_years:
            before = None  # behind on the newest side — fetch the latest 10-K
        elif (
            filing_dates
            and latest_fiscal_year is not None
            and stored_years
            and min(stored_years) <= latest_fiscal_year - (_MAX_HISTORY_YEARS - 1)
        ):
            # Already have `_MAX_HISTORY_YEARS` years on file — matches the
            # Income Statement table's own display window, so anything
            # older would never be shown. Stop spending iterations/SEC
            # downloads/LLM calls walking further into the past.
            run_caveats.append(
                f"Iteration {i + 1}/{iterations}: already have {_MAX_HISTORY_YEARS} years of AFFO "
                f"history on file (back to FY{min(stored_years)}) — matching the Income Statement "
                "table's own display window, so walking further back wouldn't be shown anywhere"
            )
            break
        elif filing_dates:
            # The filing directly preceding the one already processed
            # always re-reports some of our newest known years — walking
            # back one filing at a time re-derives the same overlap
            # forever. `years_per_table` (learned from this company's own
            # first successful extraction, not guessed) tells us exactly
            # how many filing-steps of overlap to walk past. Each peek only
            # reads a filing's own "FILED AS OF DATE" header (no LLM) —
            # cheap, since the expensive part (the LLM call) only happens
            # once, on the final (non-overlapping) filing.
            steps_to_skip = (years_per_table - 1) if years_per_table else 1
            cursor = min(filing_dates)
            for _ in range(steps_to_skip):
                peek = await asyncio.to_thread(get_affo_reconciliation_text, symbol, cursor)
                if peek is None:
                    break
                skip_candidate = peek
                cursor = peek[1]
            before = cursor
        else:
            before = None  # never fetched anything for this symbol yet

        extraction_result = await asyncio.to_thread(get_affo_reconciliation_text, symbol, before)
        if extraction_result is None:
            run_caveats.append(
                f"Iteration {i + 1}/{iterations}: no reconciliation table found"
                + (f" in any 10-K filed before {before}" if before else " in the latest 10-K")
            )
            break  # nothing more to gain from further iterations right now

        table_text, filed_date = extraction_result
        if filed_date in filing_dates:
            # Already processed this exact filing in an earlier refresh —
            # SEC EDGAR has nothing older to offer from here. Stop cleanly
            # instead of re-running the LLM on data already on file.
            run_caveats.append(f"Iteration {i + 1}/{iterations}: reached the earliest already-processed filing ({filed_date})")
            break

        llm_result = await _affo_extraction_agent.run(f"Ticker: {symbol}\n\n10-K reconciliation table:\n{table_text}")
        extraction = llm_result.output
        # Don't trust the LLM's own list order — the source table itself
        # can list years newest-first, so a plain [-1] for "latest" would
        # silently pick the oldest year instead.
        extraction.historical_data.sort(key=lambda y: y.fiscal_year)

        # Learn (once) how many comparative fiscal years this company's own
        # 10-K table actually contains, straight from the raw extraction
        # before any of the discard/dedup logic below can shrink it — a
        # real fact about this filing, not a guess. Kept for the rest of
        # this symbol's life (persisted on the report below) since a
        # company only rarely changes how many years it reports; the
        # backward-walk skip above uses it directly instead of assuming a
        # fixed count.
        if years_per_table is None and extraction.historical_data:
            years_per_table = len(extraction.historical_data)

        # Within a SINGLE extraction — no prior stored history to compare
        # against, so the cross-run checks further down never get a chance
        # to fire — two ADJACENT fiscal years can come back with
        # byte-identical AFFO/share: the model reading one table column
        # into both output rows. There's no reliable way to tell which of
        # the two (if either) is the genuine value, so both are discarded
        # rather than guessing — same "flag, don't guess" principle as the
        # cross-run duplicate check below.
        _dupe_years: set[int] = set()
        for a, b in zip(extraction.historical_data, extraction.historical_data[1:]):
            if a.affo_per_share is not None and a.affo_per_share == b.affo_per_share:
                _dupe_years.add(a.fiscal_year)
                _dupe_years.add(b.fiscal_year)
        if _dupe_years:
            extraction.historical_data = [y for y in extraction.historical_data if y.fiscal_year not in _dupe_years]
            run_caveats.append(
                f"Iteration {i + 1}/{iterations}: discarded FY{', FY'.join(str(y) for y in sorted(_dupe_years))} "
                "— this extraction reported identical AFFO/share for adjacent fiscal years within the "
                "same filing, almost certainly the model reading one table column into both; re-run "
                "Analyze to retry"
            )

        # Re-extracting the EXACT same table on a later run can produce
        # identical dollar figures but with fiscal years shifted by a
        # constant offset (e.g. a table whose own header reads "2025 |
        # 2024" gets labeled FY2023/FY2024 instead of FY2024/FY2025) — the
        # LLM's year-labeling isn't reliably deterministic for the same
        # input. When fetching the latest 10-K
        # (before is None), FMP's own `latest_fiscal_year` is a reliable,
        # independent anchor — if the extraction's newest row doesn't match
        # it, the whole batch is shifted by the same offset to correct it
        # (the relative ordering within one table was still right, just
        # anchored wrong). Walking backward has no such anchor, so an
        # overlapping year that disagrees with what's already on file is
        # flagged instead of auto-corrected.
        if extraction.historical_data:
            max_extracted_year = extraction.historical_data[-1].fiscal_year
            if before is None and latest_fiscal_year is not None and max_extracted_year != latest_fiscal_year:
                offset = latest_fiscal_year - max_extracted_year
                for y in extraction.historical_data:
                    y.fiscal_year += offset
                run_caveats.append(
                    f"Iteration {i + 1}/{iterations}: corrected a {offset:+d}-year labeling offset "
                    f"(extraction labeled the newest row FY{max_extracted_year}, but FMP's latest "
                    f"reported fiscal year is FY{latest_fiscal_year})"
                )
            elif before is not None:
                for y in extraction.historical_data:
                    existing = next((h for h in history if h.fiscal_year == y.fiscal_year), None)
                    if existing and existing.affo_per_share and y.affo_per_share:
                        rel_diff = abs(existing.affo_per_share - y.affo_per_share) / abs(existing.affo_per_share)
                        if rel_diff > 0.05:
                            run_caveats.append(
                                f"Iteration {i + 1}/{iterations}: FY{y.fiscal_year} AFFO/share from this "
                                f"extraction ({y.affo_per_share}) disagrees with what's already on file "
                                f"({existing.affo_per_share}) — possible year-labeling error, not "
                                "auto-corrected (no independent anchor for backward-walk iterations)"
                            )

        # A genuinely NEW fiscal year (no prior stored value to diff
        # against, so the overlap check above doesn't fire) that comes back
        # with AFFO/share byte-identical to the immediately adjacent
        # already-stored year — despite a materially different diluted
        # share count that year — is a mislabeling artifact (the model
        # echoed the neighboring column), not a real coincidence: two
        # distinct fiscal years landing on the exact same AFFO/share to the
        # cent is not something a real REIT produces. Discarded rather than
        # trusted, with no attempt to guess the real value.
        stored_by_year = {h.fiscal_year: h for h in history}
        suspect_years = [
            y.fiscal_year
            for y in extraction.historical_data
            if y.fiscal_year not in stored_by_year
            for adjacent in [stored_by_year.get(y.fiscal_year - 1) or stored_by_year.get(y.fiscal_year + 1)]
            if adjacent and y.affo_per_share is not None and adjacent.affo_per_share is not None
            and y.affo_per_share == adjacent.affo_per_share
        ]
        if suspect_years:
            extraction.historical_data = [y for y in extraction.historical_data if y.fiscal_year not in suspect_years]
            # Whether a later refresh can actually retry THIS filing for the
            # discarded year(s) depends on whether anything else from it
            # survived — see the `filing_dates` update below, which only
            # marks it processed when it did.
            retry_note = (
                "this filing will be re-fetched and re-extracted on a later refresh (nothing else "
                "usable came from it this time)"
                if not extraction.historical_data
                else "this filing already contributed other usable years, so it won't be re-fetched "
                "automatically — delete and re-analyze this symbol to force a retry"
            )
            run_caveats.append(
                f"Iteration {i + 1}/{iterations}: discarded FY{', FY'.join(str(y) for y in suspect_years)} — "
                "AFFO/share came back identical to the adjacent already-stored fiscal year, almost "
                f"certainly a mislabeled/duplicated extraction rather than a real value; {retry_note}"
            )

        # The two checks above only catch a year colliding with an
        # ALREADY-KNOWN value (duplicated within this extraction, or
        # matching a previously-stored year) — neither catches two
        # DIFFERENT extracted values simply swapped between their two year
        # labels. `net_income` is required from every extraction and is
        # also one of FMP's own reported per-year fields with no LLM
        # involved — the most reliable independent anchor available, so a
        # mismatch here is strong evidence the year label (not just the
        # AFFO figure) is wrong. Flagged only, not auto-corrected: unlike
        # the single uniform-offset case above, there's no safe way to know
        # *which* years are actually swapped with which from this alone.
        for y in extraction.historical_data:
            fmp_value = fmp_net_income_by_fy.get(y.fiscal_year)
            if y.net_income is None or fmp_value is None or fmp_value == 0:
                continue
            rel_diff = abs(y.net_income * 1000 - fmp_value) / abs(fmp_value)
            if rel_diff > 0.15:
                run_caveats.append(
                    f"Iteration {i + 1}/{iterations}: FY{y.fiscal_year} net income from this extraction "
                    f"({y.net_income * 1000:,.0f}) doesn't match FMP's reported net income for that "
                    f"fiscal year ({fmp_value:,.0f}) — the year label on this row may be wrong "
                    "(e.g. swapped with an adjacent year); verify before trusting this row"
                )

        if not extraction.historical_data:
            if not suspect_years and not _dupe_years:  # already explained by a caveat above otherwise
                run_caveats.append(
                    f"Iteration {i + 1}/{iterations}: reconciliation table found ({filed_date}) but no "
                    "fiscal-year rows could be extracted from it"
                )
        else:
            missing_affo_ps = sum(1 for y in extraction.historical_data if y.affo_per_share is None)
            if missing_affo_ps:
                run_caveats.append(
                    f"Iteration {i + 1}/{iterations}: AFFO/share missing for {missing_affo_ps} of "
                    f"{len(extraction.historical_data)} years extracted from the {filed_date} filing"
                )

        history = _merge_history(history, extraction.historical_data)
        # Only mark this filing "processed" if it actually contributed
        # something, OR its table was genuinely empty of fiscal-year rows.
        # If every row this filing produced got discarded above as a
        # suspected mislabeling artifact, leave it off `filing_dates` so a
        # later refresh re-fetches and re-extracts the SAME filing (giving
        # the non-deterministic LLM another attempt) instead of treating it
        # as done and permanently skipping the fiscal year it should have
        # covered.
        if extraction.historical_data or not (suspect_years or _dupe_years):
            filing_dates = sorted(set(filing_dates) | {filed_date})
        metric_name = extraction.metric_name_used_by_company or metric_name
        iterations_done += 1

        # Defense-in-depth, not the primary mechanism: the skip above now
        # walks by the company's own measured `years_per_table`, not a
        # guess, so a gap shouldn't normally happen. Still checked for in
        # case a company changes its reporting format mid-history — the
        # last skipped-past filing's table is already sitting in memory
        # (`skip_candidate`, downloaded earlier this same iteration just to
        # read its date) — run the LLM on it now to fill the hole instead
        # of leaving a silent gap.
        sorted_years = sorted(y.fiscal_year for y in history)
        gap_years = [b for a, b in zip(sorted_years, sorted_years[1:]) if b - a > 1]
        if gap_years and skip_candidate is not None:
            fallback_text, fallback_filed_date = skip_candidate
            fallback_result = await _affo_extraction_agent.run(
                f"Ticker: {symbol}\n\n10-K reconciliation table:\n{fallback_text}"
            )
            if fallback_result.output.historical_data:
                history = _merge_history(history, fallback_result.output.historical_data)
                filing_dates = sorted(set(filing_dates) | {fallback_filed_date})
                run_caveats.append(
                    f"Iteration {i + 1}/{iterations}: the skip-ahead left a gap around FY{gap_years[0]} "
                    f"— filled it using the filing that was skipped ({fallback_filed_date}), which "
                    "apparently covers a different number of comparative years than assumed"
                )

    # Trim to the newest `_MAX_HISTORY_YEARS` years every run, not just at
    # the backward-walk boundary above — that check only stops future
    # backward walks from adding more old years, but does nothing to the
    # forward-growth side. A REIT already sitting at 15 years on file would
    # otherwise grow to 16, 17... forever as each new annual 10-K appears,
    # since `_merge_history` only ever adds/overwrites. This keeps the
    # stored window sliding forward in lockstep with the Income Statement
    # table's own 15-year display window instead.
    if len(history) > _MAX_HISTORY_YEARS:
        history = sorted(history, key=lambda y: y.fiscal_year)[-_MAX_HISTORY_YEARS:]

    confidence = 1.0
    if not history:
        confidence = 0.2  # at least one table existed but nothing usable came out of any iteration
    else:
        total_fields = len(history) * 6
        missing_fields = sum(
            1
            for y in history
            for v in (y.net_income, y.ffo, y.ffo_per_share, y.affo, y.affo_per_share, y.diluted_shares)
            if v is None
        )
        confidence = round(max(0.3, 1.0 - missing_fields / total_fields), 2)

    latest = history[-1] if history else None
    summary = (
        f"{symbol}: {metric_name or 'AFFO'}/share {latest.affo_per_share if latest else 'n/a'} "
        f"(FY{latest.fiscal_year if latest else 'n/a'}), {len(history)} fiscal years on file "
        f"({iterations_done} filing(s) processed this run, accumulated across refreshes)."
        if latest
        else f"{symbol}: no usable AFFO data on file yet."
    )

    return AFFOReport(
        symbol=symbol,
        is_reit=True,
        latest_annual_report_date=latest_annual_report_date,
        data_source="sec_edgar, fmp",  # reconciliation table from SEC EDGAR, net-income cross-check from FMP — always both, not a fallback pair
        metric_name_used_by_company=metric_name,
        historical_data=history,
        processed_filing_dates=filing_dates,
        years_per_table=years_per_table,
        confidence=confidence,
        caveats=run_caveats,
        summary=summary,
    )
