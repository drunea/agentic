"""Earnings call transcript fetch — multiple providers, tried in
EARNINGS_CALL_PROVIDER_ORDER (.env) order, falling back to the next one
only on a real failure (exception/non-2xx/not-found), never just because
a provider has nothing for this symbol.

roic.ai (`roic`) is preferred — richer per-speaker transcript structure,
flattened to plain text here to keep the same interface FMP already used.
Free tier only exposes the 2 most recent quarters per company (a
data-availability window, not a call counter — verified live: the 2 most
recent quarters are fetchable repeatedly, a 3rd/older one 402s), which is
fine here since only the latest quarter is ever requested.

FMP legacy (`fmp`) is the fallback — the endpoint FMP has said will
eventually be retired, kept as a safety net rather than the primary.

Both providers resolve "latest transcript" and "transcript text" together
per call (`_fetch_roic`/`_fetch_fmp` below), NOT as two independently
fallback-able steps — mixing providers between the two steps (e.g. roic's
latest quarter fed into FMP's text fetch) risks asking one provider for a
quarter it was never told to have, so whichever provider succeeds for
"latest info" is also the one used for "transcript text" in that run.
"""

import asyncio

import httpx

from agentic.config import settings
from agentic.data.fmp_client import fmp_get

# (quarter, year, call_date, transcript_text, provider_name)
_TranscriptResult = tuple[int, int, str | None, str, str]


async def _resolve_roic_identifier(symbol: str) -> str | None:
    """roic.ai identifies companies as "EXCHANGE:SYMBOL" (e.g. "NASDAQ:AAPL"),
    not the bare ticker this app uses everywhere else — resolved via their
    ticker search, taking the primary listing.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.roicai_base_url}/tickers/search",
            params={"apikey": settings.roicai_api_key, "query": symbol, "format": "json"},
        )
        response.raise_for_status()
    for row in response.json().get("data", []):
        if row.get("symbol", "").split(":")[-1].upper() == symbol.upper():
            return row.get("primary_symbol") or row.get("symbol")
    return None


async def _fetch_roic(symbol: str) -> _TranscriptResult | None:
    identifier = await _resolve_roic_identifier(symbol)
    if identifier is None:
        return None

    async with httpx.AsyncClient(timeout=30) as client:
        list_response = await client.get(
            f"{settings.roicai_base_url}/earnings-calls",
            params={"apikey": settings.roicai_api_key, "identifier": identifier, "order": "desc"},
        )
        list_response.raise_for_status()
        latest = (list_response.json().get("data") or [None])[0]
        if latest is None:
            return None

        quarter, year, call_date = latest["fiscal_quarter"], latest["fiscal_year"], latest.get("date")
        transcript_response = await client.get(
            f"{settings.roicai_base_url}/earnings-calls/{identifier}",
            params={"apikey": settings.roicai_api_key, "fiscal_year": year, "fiscal_quarter": quarter, "format": "json"},
        )
        transcript_response.raise_for_status()
        turns = transcript_response.json().get("transcript") or []

    text = "\n\n".join(f"{t.get('speaker', 'Unknown')}: {t.get('text', '')}" for t in turns)
    if not text:
        return None
    return int(quarter), int(year), call_date, text, "roic"


async def _fetch_fmp(symbol: str) -> _TranscriptResult | None:
    raw = await asyncio.to_thread(fmp_get, "earning_call_transcript", legacy_version="v4", symbol=symbol)
    if not isinstance(raw, list) or not raw:
        return None
    quarter, year, call_date = raw[0]
    quarter, year = int(quarter), int(year)

    raw_text = await asyncio.to_thread(
        fmp_get, f"earning_call_transcript/{symbol}", legacy_version="v3", year=year, quarter=quarter
    )
    if not isinstance(raw_text, list) or not raw_text:
        return None
    text = raw_text[0].get("content")
    if not text:
        return None
    return quarter, year, call_date, text, "fmp"


_FETCHERS = {"roic": _fetch_roic, "fmp": _fetch_fmp}


def _provider_order() -> list[str]:
    return [p.strip() for p in settings.earnings_call_provider_order.split(",") if p.strip()]


# Both `_fetch_roic`/`_fetch_fmp` already return info+text together in one
# shot — caches that whole result per symbol so the public two-step
# interface below (mirroring the old FMP-only shape, which the analyst
# layer calls as two separate steps) doesn't re-run the whole fetch
# (ticker resolution + list + transcript) twice for one `analyze_earnings_
# call` run. Small and process-lifetime only; a stale entry just means one
# extra live re-fetch if a new quarter was reported in between, handled by
# the mismatch check in get_transcript_text.
_last_fetch_cache: dict[str, _TranscriptResult] = {}


async def _fetch(symbol: str) -> _TranscriptResult | None:
    for name in _provider_order():
        fetcher = _FETCHERS.get(name)
        if fetcher is None:
            continue
        try:
            result = await fetcher(symbol)
        except Exception:
            continue
        if result is not None:
            _last_fetch_cache[symbol] = result
            return result
    return None


async def get_latest_transcript_info(symbol: str) -> tuple[int, int, str | None, str] | None:
    """Returns (quarter, year, call_date, provider_name) for the most recent
    transcript found. `provider_name` must be passed back into
    `get_transcript_text` so the same provider serves both steps of one run.
    """
    result = await _fetch(symbol)
    if result is None:
        return None
    quarter, year, call_date, _text, provider = result
    return quarter, year, call_date, provider


async def get_transcript_text(symbol: str, quarter: int, year: int, provider: str) -> str | None:
    cached = _last_fetch_cache.get(symbol)
    if cached is None or cached[0] != quarter or cached[1] != year or cached[4] != provider:
        fetcher = _FETCHERS.get(provider)
        if fetcher is None:
            return None
        try:
            cached = await fetcher(symbol)
        except Exception:
            return None
        if cached is None:
            return None
        _last_fetch_cache[symbol] = cached

    result_quarter, result_year, _call_date, text, _provider = cached
    if result_quarter != quarter or result_year != year:
        # The provider's "latest" moved on since get_latest_transcript_info
        # ran (a new quarter reported in between) — refuse rather than
        # silently return the wrong quarter's text under the old label.
        return None
    return text
