from agentic.data.base import DataProvider


class FakeDataProvider(DataProvider):
    """Minimal DataProvider double: returns whatever's handed to it at
    construction instead of hitting a real market-data API.
    """

    name = "fake"

    def __init__(self, *, quote=None, history=None, fundamentals=None, news=None):
        self._quote = quote or {}
        self._history = history or []
        self._fundamentals = fundamentals or {}
        self._news = news or []

    async def get_quote(self, symbol: str) -> dict:
        return self._quote

    async def get_history(self, symbol: str, period: str = "1y") -> list[dict]:
        return self._history

    async def get_fundamentals(self, symbol: str) -> dict:
        return self._fundamentals

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict]:
        return self._news
