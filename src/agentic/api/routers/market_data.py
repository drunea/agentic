"""Raw market data — no LLM involved, so charts don't pay agent latency."""

from fastapi import APIRouter

from agentic.data.chain import ProviderChain
from agentic.tools.market_data import normalize_price_history
from agentic.tools.market_news import get_cached_market_news

router = APIRouter()


@router.get("/history/{symbol}")
async def get_history(symbol: str, period: str = "6mo") -> list[dict]:
    history = await ProviderChain().get_history(symbol, period=period)
    return normalize_price_history(history)


@router.get("/market-news/{symbol}")
async def market_news(symbol: str, max_age_hours: int = 24) -> list[dict]:
    """Reads from the shared global news cache, filtered to this symbol and
    to the last `max_age_hours` — see tools/market_news.py for why this
    isn't a per-symbol FMP call.
    """
    return await get_cached_market_news(symbol, max_age_hours=max_age_hours)
