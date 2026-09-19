"""yfinance-backed implementation of the DataProvider interface.

Free, no API key — used as the primary provider in the fallback chain.
"""

import asyncio

import yfinance as yf

from agentic.data.base import DataProvider


class YFinanceProvider(DataProvider):
    name = "yfinance"

    async def get_quote(self, symbol: str) -> dict:
        return await asyncio.to_thread(self._get_quote_sync, symbol)

    @staticmethod
    def _get_quote_sync(symbol: str) -> dict:
        info = yf.Ticker(symbol).fast_info
        return {
            "symbol": symbol,
            "price": info.get("lastPrice"),
            "previousClose": info.get("previousClose"),
            "dayHigh": info.get("dayHigh"),
            "dayLow": info.get("dayLow"),
            "yearHigh": info.get("yearHigh"),
            "yearLow": info.get("yearLow"),
            "volume": info.get("lastVolume"),
            "marketCap": info.get("marketCap"),
            "_provider": "yfinance",
        }

    async def get_history(self, symbol: str, period: str = "1y") -> list[dict]:
        return await asyncio.to_thread(self._get_history_sync, symbol, period)

    @staticmethod
    def _get_history_sync(symbol: str, period: str) -> list[dict]:
        df = yf.Ticker(symbol).history(period=period).reset_index()
        df["Date"] = df["Date"].astype(str)
        rows = df.to_dict(orient="records")
        for row in rows:
            row["_provider"] = "yfinance"
        return rows

    async def get_fundamentals(self, symbol: str) -> dict:
        """Normalized to the same keys FMPProvider uses, so a caller doesn't
        care which provider actually answered.
        """
        return await asyncio.to_thread(self._get_fundamentals_sync, symbol)

    @staticmethod
    def _get_fundamentals_sync(symbol: str) -> dict:
        info = yf.Ticker(symbol).info
        fcf = info.get("freeCashflow")
        shares = info.get("sharesOutstanding")
        return {
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "fcf_per_share": (fcf / shares) if fcf and shares else None,
            "market_cap": info.get("marketCap"),
            "_provider": "yfinance",
        }

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict]:
        return await asyncio.to_thread(self._get_news_sync, symbol, limit)

    @staticmethod
    def _get_news_sync(symbol: str, limit: int) -> list[dict]:
        items = yf.Ticker(symbol).news[:limit]
        return [
            {
                "title": item.get("content", {}).get("title", ""),
                "published_date": item.get("content", {}).get("pubDate"),
                "_provider": "yfinance",
            }
            for item in items
            if item.get("content", {}).get("title")
        ]
