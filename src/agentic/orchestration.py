"""Central registry of specialists, freshness policy, and refresh execution
for the per-symbol `company_analysis` snapshot.

Each specialist is a plain `analyze(provider, symbol) -> Report` coroutine
(some are zero/single-LLM-call, some still bridge to an old tool-loop Agent
— see sentiment_analyst.py's `analyze_*` wrapper).
`refresh_company()` runs whichever subset the caller asks for, writes each
specialist's result into its own key of `CompanyAnalysis.specialists` as it
completes (not all-or-nothing), and — once every base specialist is fresh —
runs one more LLM call for cross-signal contradictions + a top-level
summary. Only one `refresh_company()` runs at a time per symbol — the
caller (the `/refresh` route) acquires a DB-backed lock before scheduling
this as a background task; see `repository.try_acquire_refresh_lock()`.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agentic import health
from agentic.agents.affo_analyst import analyze_affo
from agentic.agents.data_collector import analyze_data_collector
from agentic.agents.disruption_analyst import analyze_disruption
from agentic.agents.earnings_analyst import analyze_earnings
from agentic.agents.earnings_call_analyst import analyze_earnings_call
from agentic.agents.financial_statements_analyst import analyze_financial_statements
from agentic.agents.performance_analyst import analyze_performance
from agentic.agents.risk_analyst import analyze_risk
from agentic.agents.sentiment_analyst import analyze_sentiment
from agentic.agents.technical_analyst import analyze_technical
from agentic.agents.valuation_analyst import analyze_valuation
from agentic.data.base import DataProvider
from agentic.data.chain import ProviderChain
from agentic.db import repository
from agentic.db.session import SessionLocal
from agentic.llm import get_model
from agentic.schemas.orchestrator import Contradiction
from agentic.tools.company_profile import get_company_profile

logger = logging.getLogger(__name__)

SpecialistFn = Callable[[DataProvider, str], Awaitable[BaseModel]]


SPECIALISTS: dict[str, SpecialistFn] = {
    "data_collector": analyze_data_collector,
    "technical": analyze_technical,
    "risk": analyze_risk,
    "performance": analyze_performance,
    "earnings": analyze_earnings,
    "valuation": analyze_valuation,
    "financial_statements": analyze_financial_statements,
    "affo": analyze_affo,
    "earnings_call": analyze_earnings_call,
    "disruption": analyze_disruption,
    "sentiment": analyze_sentiment,
}

# Which specialists must be "done" before the cross-signal step fires — a
# separate, smaller set from `SPECIALISTS`: while only Fundamental Deep
# Dive, Technical Charts, and Sentiment & News are being built out, gating
# on all specialists would mean the Stock Analysis page could never trigger
# cross-signal at all, since the rest only get refreshed from their own
# dedicated pages. Kept in lockstep with `_VISIBLE_SPECIALISTS` in
# frontend/pages/1_Stock_Analysis.py. Revisit once more specialists are
# back in active use.
_CROSS_SIGNAL_REQUIRED = {
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
}

# How long a "done" result stays valid before it's considered stale, per
# specialist — they don't all change at the same pace. "financial_statements"
# is deliberately absent: it uses a different rule entirely (see
# _financial_statements_expired below), not a fixed TTL from updated_at.
FRESHNESS_SECONDS: dict[str, int] = {
    "data_collector": 5 * 60,
    "technical": 60 * 60,
    "risk": 6 * 60 * 60,
    "performance": 6 * 60 * 60,
    "earnings": 24 * 60 * 60,
    "sentiment": 2 * 60 * 60,
    "valuation": 24 * 60 * 60,
    "disruption": 6 * 60 * 60,
}
_ORCHESTRATOR_FRESHNESS_SECONDS = 60 * 60

# financial_statements freshness is judged against the company's own last
# *reporting* date (stored in the result), not against when we last fetched
# it — a report doesn't go stale just because time passed since our last
# check; it goes stale when the company issues a newer one. Annual reports
# come out ~once a year, so 11 months gives a margin before the next one is
# due; quarterly ones every ~90 days, so 75 gives a similar margin.
_ANNUAL_REPORT_STALE_DAYS = 335  # ~11 months
_QUARTERLY_REPORT_STALE_DAYS = 75


def _financial_statements_expired(entry: dict | None) -> bool:
    if entry is None or entry.get("status") != "done":
        return True
    result = entry.get("result") or {}
    now = datetime.now(timezone.utc)

    annual_date = result.get("latest_annual_report_date")
    if not annual_date:
        return True
    annual_age_days = (now - datetime.fromisoformat(annual_date).replace(tzinfo=timezone.utc)).days
    if annual_age_days > _ANNUAL_REPORT_STALE_DAYS:
        return True

    quarterly_date = result.get("latest_quarterly_report_date")
    if not quarterly_date:
        return True
    quarterly_age_days = (now - datetime.fromisoformat(quarterly_date).replace(tzinfo=timezone.utc)).days
    return quarterly_age_days > _QUARTERLY_REPORT_STALE_DAYS


def _affo_expired(entry: dict | None) -> bool:
    """Same reasoning as financial_statements — judged against the last
    *annual* report date (AFFO comes from the 10-K, filed once a year),
    not `updated_at`. No quarterly component: 10-Qs don't carry the AFFO
    reconciliation table this extracts from.
    """
    if entry is None or entry.get("status") != "done":
        return True
    result = entry.get("result") or {}
    annual_date = result.get("latest_annual_report_date")
    if not annual_date:
        return True
    now = datetime.now(timezone.utc)
    age_days = (now - datetime.fromisoformat(annual_date).replace(tzinfo=timezone.utc)).days
    return age_days > _ANNUAL_REPORT_STALE_DAYS


_EARNINGS_CALL_STALE_DAYS = 100  # ~quarterly cadence (90d) + margin


def _earnings_call_expired(entry: dict | None) -> bool:
    """Judged against the call's own `call_date` — a new call only happens
    ~quarterly, so re-running this before the next one exists would just
    re-analyze the same transcript for no reason.
    """
    if entry is None or entry.get("status") != "done":
        return True
    result = entry.get("result") or {}
    call_date = result.get("call_date")
    if not call_date:
        return True
    now = datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(call_date)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).days > _EARNINGS_CALL_STALE_DAYS


# Specialists whose expiry can't be judged by a flat updated_at + TTL.
_CUSTOM_EXPIRY: dict[str, Callable[[dict | None], bool]] = {
    "financial_statements": _financial_statements_expired,
    "affo": _affo_expired,
    "earnings_call": _earnings_call_expired,
}


class _CrossSignalResult(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)
    summary: str


_cross_signal_agent = Agent(
    get_model("orchestrator"),
    output_type=_CrossSignalResult,
    retries={"output": 3},
    system_prompt=(
        "You are the lead research orchestrator. You are given structured "
        "reports already produced by several specialists for one company. Compare "
        "their conclusions: if two specialists disagree (e.g. bullish "
        "technical trend vs negative sentiment tone, high risk level vs "
        "strong backtest returns, a 'disruptor' posture vs a deteriorating "
        "earnings trend, or one specialist has much lower confidence than "
        "the others), record each such disagreement as a contradiction "
        "naming the agents involved.\n\n"
        "Then write the top-level summary in two clearly labeled parts, "
        "since a stock can look attractive on one horizon and weak on the "
        "other — collapsing both into one undifferentiated paragraph hides "
        "that:\n"
        "- 'Short-term (1-3 months): ...' — grounded in technical (trend, "
        "momentum indicators), earnings (recent surprises, upcoming report "
        "date, analyst grade changes), and risk/performance's volatility "
        "and drawdown figures.\n"
        "- 'Long-term (3-5 years): ...' — grounded in financial_statements "
        "and affo (ROIC vs WACC, whether the company is value-creating or "
        "value-destroying, capital return policy), risk's solvency signals "
        "(Altman Z-Score, Piotroski F-Score, leverage), and disruption's "
        "competitive posture.\n"
        "Each part should be a few sentences, not a single line — synthesize "
        "across the relevant specialists rather than just listing their "
        "individual conclusions. If a horizon's specialists haven't run, "
        "say so briefly instead of guessing. Respond ONLY with the required "
        "structured output — never plain prose outside these two labeled parts."
    ),
)


def is_expired(entry: dict | None, specialist: str) -> bool:
    if specialist in _CUSTOM_EXPIRY:
        return _CUSTOM_EXPIRY[specialist](entry)
    if entry is None or entry.get("status") != "done":
        return True
    updated_at = entry.get("updated_at")
    if not updated_at:
        return True
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds()
    return age > FRESHNESS_SECONDS.get(specialist, 24 * 60 * 60)


def _json_sanitize(value):
    """Replaces NaN/Infinity floats with None, recursively — Python's `json`
    module (and pydantic's `model_dump(mode="json")`) happily emits the
    literal tokens `NaN`/`Infinity`, which are valid Python but not valid
    JSON; MySQL's JSON column type rejects them outright on write
    ("Invalid JSON text"), which failed a `db.commit()` deep inside a
    background task with no caller left to see the exception (see the
    `db.rollback()` note below for why that then looked like a silent
    hang, not an error). Applied once here rather than chasing down every
    individual division in every specialist that could produce one.
    """
    if isinstance(value, float):
        return None if (value != value or value in (float("inf"), float("-inf"))) else value
    if isinstance(value, dict):
        return {k: _json_sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_sanitize(v) for v in value]
    return value


async def run_specialist(symbol: str, specialist: str, **kwargs) -> None:
    """Runs one specialist, writing status transitions as it goes. Own DB
    session — this runs inside a FastAPI BackgroundTask, not a request.

    `**kwargs`: extra per-specialist refresh-time options (today, only
    `affo` accepts `iterations` — see `RefreshRequest.affo_iterations`).
    Every other specialist's `analyze_*` function takes just
    `(provider, symbol)`, so kwargs are only forwarded when actually given.
    """
    fn = SPECIALISTS[specialist]
    db = SessionLocal()
    try:
        # Preserve the prior `result`/`updated_at` across the "running"
        # transition: AFFO's own `_load_previous_state` reads this same row
        # mid-run to accumulate history across refreshes, so nulling
        # `result` here before `fn()` even starts would make every AFFO
        # refresh see an empty history and start over from scratch. No page
        # reads `result`/`updated_at` while status is "running" (they show
        # a polling message instead), so keeping them around is safe for
        # every other specialist too.
        existing = repository.get_company_analysis(db, symbol)
        prior_entry = (existing.specialists or {}).get(specialist) if existing else None
        prior_entry = prior_entry or {}
        repository.set_specialist_entry(
            db,
            symbol,
            specialist,
            {
                "status": "running",
                "result": prior_entry.get("result"),
                "error": None,
                "updated_at": prior_entry.get("updated_at"),
            },
        )
        report = await (fn(ProviderChain(), symbol, **kwargs) if kwargs else fn(ProviderChain(), symbol))
        repository.set_specialist_entry(
            db,
            symbol,
            specialist,
            {
                "status": "done",
                "result": _json_sanitize(report.model_dump(mode="json")),
                "error": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await health.record_success(specialist)
    except Exception as exc:  # noqa: BLE001 - background task must never raise into the loop
        logger.exception("Specialist '%s' failed for %s", specialist, symbol)
        # A failed commit above (e.g. the NaN/Infinity case _json_sanitize
        # now prevents, but potentially other causes too) leaves this
        # session's transaction rolled back — reusing it without an
        # explicit rollback() raises PendingRollbackError here instead of
        # actually recording the error, which is exactly how a real
        # failure went silent and looked like a permanent "running" hang.
        db.rollback()
        repository.set_specialist_entry(
            db,
            symbol,
            specialist,
            {
                "status": "error",
                "result": None,
                "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await health.record_failure(specialist, symbol, f"{type(exc).__name__}: {exc}")
    finally:
        db.close()


# financial_statements' full result carries 6 large nested statement tables
# (thousands of individual values) that have no "conclusion" to contradict
# anything else with — only its summary/capital_efficiency are relevant to
# cross-signal synthesis. Feeding the raw tables in would bloat the prompt
# for no benefit; trim to the parts worth comparing against other specialists.
def _latest_row_values(table: dict) -> dict:
    """The 3 giant statement tables are excluded below entirely (no per-row
    "conclusion" to compare against other specialists), but capital_return
    is small (a handful of rows) and does carry real conclusions (payout
    ratio, dividend growth) — worth the LLM seeing, just as latest-year
    scalars rather than the full per-year array.
    """
    return {row["label"]: (row["values"][-1] if row["values"] else None) for row in table.get("rows", [])}


_FILING_CITATION_FIELDS = {"valuation": "filing_citations", "disruption": "filing_insights"}


def _cross_signal_view(specialist: str, result: dict) -> dict:
    if specialist == "financial_statements":
        return {
            "summary": result.get("summary"),
            "confidence": result.get("confidence"),
            "caveats": result.get("caveats"),
            "capital_efficiency": result.get("capital_efficiency"),
            "capital_return_latest_fy": _latest_row_values(result.get("capital_return", {})),
        }
    if specialist == "affo":
        # Trimmed to just the latest fiscal year's data point, the same way
        # financial_statements is trimmed above — passing the WHOLE
        # `historical_data` array (every accumulated fiscal year, up to 15)
        # into the cross-signal prompt risks the LLM picking the wrong year
        # out of that array, since AFFO's own year-labeling isn't always
        # reliable to begin with.
        history = result.get("historical_data") or []
        latest = max(history, key=lambda y: y["fiscal_year"]) if history else None
        return {
            "summary": result.get("summary"),
            "confidence": result.get("confidence"),
            "caveats": result.get("caveats"),
            "is_reit": result.get("is_reit"),
            "latest_fiscal_year_data": latest,
        }
    if specialist in _FILING_CITATION_FIELDS:
        # The source excerpts (up to ~600 chars each) are for the reader on
        # the page, not the synthesis step — only the insight sentences are
        # relevant to comparing against other specialists.
        field = _FILING_CITATION_FIELDS[specialist]
        return {**result, field: [c["insight"] if isinstance(c, dict) else c for c in result.get(field) or []]}
    return result


async def run_cross_signal(symbol: str) -> None:
    db = SessionLocal()
    try:
        row = repository.get_company_analysis(db, symbol)
        if row is None:
            return
        specialists_data = {name: row.specialists.get(name) for name in SPECIALISTS}
        prior_orchestrator = row.specialists.get("_orchestrator") or {}
        # "running" written before the LLM call starts — same status
        # convention as run_specialist, so the frontend can show this step
        # as in-progress rather than it being invisible between "the last
        # specialist finished" and "the cross-signal result appears".
        repository.set_specialist_entry(
            db,
            symbol,
            "_orchestrator",
            {**prior_orchestrator, "status": "running"},
        )
    finally:
        db.close()

    prompt = f"Symbol: {symbol}\n\n" + "\n\n".join(
        f"{name}:\n{json.dumps(_cross_signal_view(name, entry.get('result')))}"
        for name, entry in specialists_data.items()
        if entry and entry.get("result")
    )

    try:
        result = await _cross_signal_agent.run(prompt)
    except Exception as exc:  # noqa: BLE001 - unprotected before this, left "_orchestrator"
        # stuck at "running" forever on any failure (Ollama timeout, output
        # validation) — same failure mode run_specialist already guards
        # against for every individual specialist, just missing here.
        logger.exception("Cross-signal synthesis failed for %s", symbol)
        await health.record_failure("_orchestrator", symbol, f"{type(exc).__name__}: {exc}")
        db_err = SessionLocal()
        try:
            repository.set_specialist_entry(
                db_err,
                symbol,
                "_orchestrator",
                {"status": "error", "error": str(exc), "updated_at": datetime.now(timezone.utc).isoformat()},
            )
        finally:
            db_err.close()
        return

    db2 = SessionLocal()
    try:
        repository.set_specialist_entry(
            db2,
            symbol,
            "_orchestrator",
            {
                "status": "done",
                "contradictions": [c.model_dump(mode="json") for c in result.output.contradictions],
                "summary": result.output.summary,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    finally:
        db2.close()
    await health.record_success("_orchestrator")


async def get_symbol_kind(symbol: str) -> str:
    """"equity" | "etf" | "fund" — checked once (FMP's profile isEtf/isFund
    flags) and cached on the row from then on, not re-checked every refresh.
    None of the specialists are built for funds (they all assume an
    operating company's own financial statements/earnings) — `refresh_company`
    below refuses to run ANY of them for an "etf"/"fund" symbol, rather than
    each specialist individually detecting this and writing its own
    "not applicable" result — a symbol whose own kind is unresolved should
    never accumulate 10 near-empty "done" specialist entries.
    """
    db = SessionLocal()
    try:
        row = repository.get_or_create_company_analysis(db, symbol)
        # `identity` was added after `symbol_kind` — a row analyzed before
        # then already has symbol_kind cached but no identity, which would
        # otherwise never backfill since the check below only runs once per
        # row. Only symbol_kind short-circuits the profile refetch here.
        if row.symbol_kind and row.identity:
            return row.symbol_kind
    finally:
        db.close()

    profile = await get_company_profile(symbol)
    kind = "etf" if profile.get("is_etf") else "fund" if profile.get("is_fund") else "equity"
    identity = {
        "company_name": profile.get("company_name"),
        "exchange": profile.get("exchange"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "description": profile.get("description"),
    }
    db = SessionLocal()
    try:
        repository.set_symbol_kind(db, symbol, kind)
        repository.set_identity(db, symbol, identity)
    finally:
        db.close()
    return kind


async def refresh_company(symbol: str, specialists_to_refresh: list[str], affo_iterations: int = 1) -> None:
    """Runs the requested specialists concurrently, then — once every base
    specialist has *some* result (status == "done") — refreshes the
    cross-signal contradictions+summary step.

    Deliberately checks presence, not freshness: gating on "every specialist
    currently non-expired" almost never fires in practice — a short-TTL
    specialist (e.g. data_collector, 5 minutes) can lapse again by the time
    a slow LLM specialist finishes in the same batch, so an all-fresh check
    stays false even though every specialist was just computed. Each
    specialist's own `updated_at`/`is_expired` is already visible per-field
    in the API response, so a viewer can judge staleness themselves; the
    cross-signal step's job is to synthesize whatever is currently stored,
    not to gatekeep on an unreachable simultaneous-freshness condition.

    Whole body runs under the per-symbol refresh lock, acquired by the
    caller (the /refresh route) before this was even scheduled as a
    background task — released in `finally` here no matter which branch
    returns or raises, so a failure partway through (an unhandled specialist
    exception can't happen, run_specialist catches its own; but e.g.
    get_symbol_kind's FMP call could) can't leave the symbol permanently
    locked for every other page's "Analyze" button.
    """
    try:
        if await get_symbol_kind(symbol) != "equity":
            return  # ETF/fund — no specialist runs, nothing written beyond symbol_kind itself

        valid = [s for s in specialists_to_refresh if s in SPECIALISTS]
        if valid:
            await asyncio.gather(
                *(
                    run_specialist(symbol, s, **({"iterations": affo_iterations} if s == "affo" else {}))
                    for s in valid
                )
            )

        db = SessionLocal()
        try:
            row = repository.get_company_analysis(db, symbol)
            all_present = row is not None and all(
                row.specialists.get(s, {}).get("status") == "done" for s in _CROSS_SIGNAL_REQUIRED
            )
        finally:
            db.close()

        if all_present:
            await run_cross_signal(symbol)
    finally:
        db = SessionLocal()
        try:
            repository.release_refresh_lock(db, symbol)
        finally:
            db.close()
