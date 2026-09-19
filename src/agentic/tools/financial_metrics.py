import asyncio

from agentic.data.base import DataProvider
from agentic.data.fmp_client import fmp_get


def _round2(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _pct(value: float | None) -> float | None:
    return round(value * 100, 2) if value is not None else None


async def get_valuation_ratios(provider: DataProvider, symbol: str) -> dict:
    """Valuation, profitability, and financial-health ratios for `symbol` —
    everything organized around the questions an investor actually asks
    (is it cheap, is it profitable, is it financially sound), not just
    whatever a single API endpoint happens to expose.

    All TTM (trailing twelve months) — `provider.get_fundamentals` returns
    raw values (its normalization is just key-name mapping across backends,
    not rounding), so every field is rounded here, at the one place every
    caller goes through, rather than duplicating `round()` calls per provider.
    The extra fields below are FMP-specific detail from the same
    already-fetched `ratios-ttm`/`key-metrics-ttm` responses (no additional
    API calls).
    """
    fundamentals = await provider.get_fundamentals(symbol)
    result = {
        "pe_ratio": _round2(fundamentals.get("pe_ratio")),
        "pb_ratio": _round2(fundamentals.get("pb_ratio")),
        "roe": _round2(fundamentals.get("roe")),
        "fcf_per_share": _round2(fundamentals.get("fcf_per_share")),
        "ps_ratio": None,
        "ev_to_ebitda": None,
        "gross_margin_pct": None,
        "operating_margin_pct": None,
        "net_margin_pct": None,
        "debt_to_equity": None,
        "current_ratio": None,
    }

    try:
        ratios, key_metrics = await asyncio.gather(
            asyncio.to_thread(fmp_get, "ratios-ttm", symbol=symbol),
            asyncio.to_thread(fmp_get, "key-metrics-ttm", symbol=symbol),
        )
        ratios0 = ratios[0] if isinstance(ratios, list) and ratios else {}
        km0 = key_metrics[0] if isinstance(key_metrics, list) and key_metrics else {}
    except Exception:  # noqa: BLE001 - extra detail only, core ratios above already succeeded
        return result

    result.update(
        {
            "ps_ratio": _round2(ratios0.get("priceToSalesRatioTTM")),
            "ev_to_ebitda": _round2(km0.get("evToEBITDATTM")),
            "gross_margin_pct": _pct(ratios0.get("grossProfitMarginTTM")),
            "operating_margin_pct": _pct(ratios0.get("operatingProfitMarginTTM")),
            "net_margin_pct": _pct(ratios0.get("netProfitMarginTTM")),
            "debt_to_equity": _round2(ratios0.get("debtToEquityRatioTTM")),
            "current_ratio": _round2(ratios0.get("currentRatioTTM")),
        }
    )
    return result


async def get_growth_metrics(symbol: str) -> dict:
    """YoY revenue/EPS growth for `symbol`, via FMP's financial-growth
    endpoint (FMP-specific, same rationale as peer_discovery.find_peers).
    """
    try:
        growth = await asyncio.to_thread(fmp_get, "financial-growth", symbol=symbol, limit=1)
    except Exception:  # noqa: BLE001
        return {"revenue_growth_pct": None, "eps_growth_pct": None}
    growth0 = growth[0] if isinstance(growth, list) and growth else {}
    return {
        "revenue_growth_pct": _pct(growth0.get("revenueGrowth")),
        "eps_growth_pct": _pct(growth0.get("epsgrowth")),
    }
