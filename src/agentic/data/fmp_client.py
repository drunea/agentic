"""Thin client for the Financial Modeling Prep (FMP) API.

Docs: https://site.financialmodelingprep.com/developer/docs
"""

import httpx

from agentic.config import settings

# Base URLs live in settings (config.py / .env: FMP_BASE_URL,
# FMP_LEGACY_BASE_URL), not as module constants — every API address is
# .env-overridable. The legacy base exists because a few endpoints
# (earnings call transcripts, the market-wide news+sentiment feed) 402/404
# on the new "stable" API but work fine on FMP's older v3/v4 API under the
# same key — the current plan just doesn't cover their "stable" equivalents.


def fmp_get(endpoint: str, *, legacy_version: str | None = None, **params: object) -> object:
    """Call an FMP endpoint and return the parsed JSON response.

    Args:
        endpoint: Path relative to the base URL, e.g. "quote".
        legacy_version: e.g. "v3" or "v4" — routes to settings.fmp_legacy_base_url
            instead of the default "stable" base. Omit for normal calls.
        **params: Query parameters for the request (e.g. symbol="AAPL").
    """
    if not settings.fmp_key:
        raise RuntimeError("FMP_KEY environment variable is not set")

    query = {k: v for k, v in params.items() if v is not None}
    query["apikey"] = settings.fmp_key

    base = f"{settings.fmp_legacy_base_url}/{legacy_version}" if legacy_version else settings.fmp_base_url
    response = httpx.get(
        f"{base}/{endpoint}",
        params=query,
        # Generous timeout: many concurrent FMP calls (asyncio.gather) plus
        # local LLM inference and SEC filing downloads running at the same
        # time can delay an otherwise-sub-second FMP round-trip well past a
        # tight ceiling, even though nothing about the FMP call itself is
        # actually slow or broken.
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
