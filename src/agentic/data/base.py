"""Common interface every market-data provider adapts to."""

from abc import ABC, abstractmethod


class DataProvider(ABC):
    name: str

    @abstractmethod
    async def get_quote(self, symbol: str) -> dict:
        ...

    @abstractmethod
    async def get_history(self, symbol: str, period: str = "1y") -> list[dict]:
        ...

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> dict:
        ...

    @abstractmethod
    async def get_news(self, symbol: str, limit: int = 20) -> list[dict]:
        ...
