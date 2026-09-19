import asyncio

from agentic.data.fmp_client import fmp_get


async def _resolve_profile_row(symbol: str) -> dict:
    """FMP's `profile` sometimes has nothing for a bare symbol that's
    actually listed on a non-US exchange (verified live: "VWRA" — a UCITS
    ETF on the LSE — returns empty, but "VWRA.L" has a full profile).
    Falls back to FMP's free `search-symbol` to find the exchange-qualified
    form and retries once, rather than giving up on the first empty result.
    """
    result = await asyncio.to_thread(fmp_get, "profile", symbol=symbol)
    if isinstance(result, list) and result:
        return result[0]

    search = await asyncio.to_thread(fmp_get, "search-symbol", query=symbol)
    if isinstance(search, list) and search:
        qualified = search[0].get("symbol")
        if qualified and qualified != symbol:
            result = await asyncio.to_thread(fmp_get, "profile", symbol=qualified)
            if isinstance(result, list) and result:
                return result[0]
    return {}


async def get_company_profile(symbol: str) -> dict:
    """Sector/industry/description/name/exchange/ETF-or-fund flag for
    `symbol`, via FMP's profile endpoint (resolving to an exchange-qualified
    symbol first if the bare one has no direct hit — see
    `_resolve_profile_row`).

    FMP-specific (not behind the DataProvider ABC) — same rationale as
    peer_discovery.find_peers: only one provider offers this data so far.
    """
    row = await _resolve_profile_row(symbol)
    return {
        "company_name": row.get("companyName"),
        "exchange": row.get("exchange"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "description": row.get("description"),
        # capital_efficiency.py::get_wacc() reads "beta"/"market_cap" from
        # this dict — FMP's own "mktCap" field is null on this plan;
        # "marketCap" is the real one.
        "beta": row.get("beta"),
        "market_cap": row.get("marketCap"),
        "is_etf": bool(row.get("isEtf")),
        "is_fund": bool(row.get("isFund")),
    }
