"""FMP-backed implementation of the DataProvider interface."""

import asyncio
from datetime import date, timedelta

from agentic.data.base import DataProvider
from agentic.data.fmp_client import fmp_get

_PERIOD_TO_DAYS = {"1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "2y": 730, "5y": 1825}


class FMPProvider(DataProvider):
    name = "fmp"

    async def get_quote(self, symbol: str) -> dict:
        result = await asyncio.to_thread(fmp_get, "quote", symbol=symbol)
        quote = result[0] if isinstance(result, list) and result else result
        quote["_provider"] = "fmp"
        return quote

    async def get_history(self, symbol: str, period: str = "1y") -> list[dict]:
        days = _PERIOD_TO_DAYS.get(period, 365)
        from_date = (date.today() - timedelta(days=days)).isoformat()
        to_date = date.today().isoformat()
        result = await asyncio.to_thread(
            fmp_get,
            "historical-price-eod/full",
            symbol=symbol,
            **{"from": from_date, "to": to_date},
        )
        rows = result if isinstance(result, list) else result.get("historical", [])
        for row in rows:
            row["_provider"] = "fmp"
        return rows

    async def get_fundamentals(self, symbol: str) -> dict:
        """Merges the `ratios-ttm` (P/E, P/B, per-share FCF) and
        `key-metrics-ttm` (ROE and other return metrics) endpoints, then
        normalizes to the same keys every DataProvider returns — so a caller
        doesn't care which provider in the fallback chain actually answered.

        Uses the **TTM** (trailing twelve months) variants, not the plain
        `ratios`/`key-metrics` endpoints — those default to the last full
        fiscal year, which can be close to a year stale by the time the
        next one is due. Cross-checked against Finviz's live figures: the
        TTM values track theirs closely; the FY-based ones did not.
        """
        ratios, key_metrics = await asyncio.gather(
            asyncio.to_thread(fmp_get, "ratios-ttm", symbol=symbol),
            asyncio.to_thread(fmp_get, "key-metrics-ttm", symbol=symbol),
        )
        ratios0 = ratios[0] if isinstance(ratios, list) and ratios else {}
        km0 = key_metrics[0] if isinstance(key_metrics, list) and key_metrics else {}
        return {
            "pe_ratio": ratios0.get("priceToEarningsRatioTTM"),
            "pb_ratio": ratios0.get("priceToBookRatioTTM"),
            "roe": km0.get("returnOnEquityTTM"),
            "fcf_per_share": ratios0.get("freeCashFlowPerShareTTM"),
            "market_cap": km0.get("marketCap"),
            "_provider": "fmp",
        }

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict]:
        result = await asyncio.to_thread(
            fmp_get, "news/stock", symbols=symbol, limit=limit
        )
        if not isinstance(result, list):
            return []
        return [
            {
                "title": item.get("title", ""),
                "published_date": item.get("publishedDate"),
                "url": item.get("url"),
                "site": item.get("site") or item.get("publisher"),
                "_provider": "fmp",
            }
            for item in result
            if item.get("title")
        ]
