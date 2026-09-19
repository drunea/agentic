"""Multi-provider fallback chain.

Implements DataProvider itself (duck-typed), so tools/agents that already
take a `provider: DataProvider` don't need to change — they just get a
provider that quietly retries a different backend on failure.
"""

from agentic.data.base import DataProvider
from agentic.data.fmp_provider import FMPProvider
from agentic.data.yfinance_provider import YFinanceProvider


class ProviderChain(DataProvider):
    name = "chain"

    def __init__(self) -> None:
        yfinance = YFinanceProvider()
        fmp = FMPProvider()
        # yfinance first where it's free and reliable; FMP first for
        # fundamentals since its ratios/key-metrics data is richer.
        self._quote_chain = [yfinance, fmp]
        self._history_chain = [yfinance, fmp]
        self._fundamentals_chain = [fmp, yfinance]
        self._news_chain = [fmp, yfinance]

    async def get_quote(self, symbol: str) -> dict:
        return await self._try(self._quote_chain, "get_quote", symbol)

    async def get_history(self, symbol: str, period: str = "1y") -> list[dict]:
        return await self._try(self._history_chain, "get_history", symbol, period=period)

    async def get_fundamentals(self, symbol: str) -> dict:
        return await self._try(self._fundamentals_chain, "get_fundamentals", symbol)

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict]:
        return await self._try(self._news_chain, "get_news", symbol, limit=limit)

    @staticmethod
    async def _try(providers: list[DataProvider], method_name: str, *args, **kwargs):
        last_exc: Exception | None = None
        for provider in providers:
            try:
                return await getattr(provider, method_name)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - deliberately broad, falls through to the next provider
                last_exc = exc
                continue
        raise RuntimeError(
            f"All providers failed for {method_name}(symbol/args={args}, {kwargs})"
        ) from last_exc
