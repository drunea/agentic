"""Market-wide news feed — no LLM, no per-symbol specialist.

This feed's content doesn't depend on which symbol's page you're on — it's
the same market-wide feed regardless — so it's backed by a global DB table
(`MarketNewsItem`), refreshed on its own TTL independent of any symbol,
with each caller filtering that table by symbol + recency instead of
calling a provider itself per page view.

Multiple providers, tried in `MARKET_NEWS_PROVIDER_ORDER` (.env) order,
falling back to the next one only on a real failure (exception/non-2xx),
never just because a provider returned zero results for the moment — an
empty result can be a genuinely quiet news day, not a broken provider.

Two provider families, because they support different query shapes:
- GLOBAL providers (Massive, FMP legacy) return the whole market-wide feed
  in one call, independent of symbol — this is what drives the shared TTL
  refresh (`MarketNewsFeedState.last_fetched_at`).
- SYMBOL-SCOPED fallback providers (NewsAPI, GNews) have no "give me
  everything" mode — they require a search query per call — so they can't
  drive the global refresh cycle. They only run as a last resort, scoped to
  the one symbol being requested right now, when every global provider has
  failed. Their result doesn't mark the global feed fresh, since it only
  covers one symbol, not the whole market.
"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import httpx

from agentic.config import settings
from agentic.data.fmp_client import fmp_get
from agentic.db import repository
from agentic.db.session import SessionLocal

_REFRESH_TTL_SECONDS = 15 * 60  # global feed changes fast, but not THAT fast
_DEFAULT_MAX_AGE_HOURS = 24  # no point showing day-old-plus general news


def _parse_published_date(raw: str | None) -> datetime | None:
    """Returns naive UTC — MySQL's DATETIME column has no tz concept, and
    mixing an aware value into a comparison against naive stored values
    raises in Python/pymysql, so every datetime in this module is naive
    UTC throughout, not just here.
    """
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _hash(url: str, symbol: str) -> str:
    return hashlib.sha256(f"{url}|{symbol}".encode()).hexdigest()


_MASSIVE_PAGE_LIMIT = 1000  # Massive's own per-page ceiling — always request the max, not the generic fetch_limit


async def _fetch_massive(limit: int, since: datetime | None) -> list[dict]:
    """No `ticker=` filter — the global, unfiltered feed. One article can
    carry multiple tickers, each with its own independent sentiment
    (`insights[]`), so it's exploded into one item per tagged ticker rather
    than collapsed into a single row.

    Ignores the caller's `limit` for the API call itself — `limit` here is
    the generic cross-provider fetch budget (100 by default), well under
    Massive's own 1000-per-page ceiling; always asking for the max reduces
    the chance a mid-cap ticker's news gets missed in a single page.
    """
    params: dict[str, object] = {"limit": _MASSIVE_PAGE_LIMIT, "apiKey": settings.massive_api_key}
    if since is not None:
        params["published_utc.gt"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{settings.massive_base_url}/v2/reference/news", params=params)
        response.raise_for_status()

    items: list[dict] = []
    for article in response.json().get("results", []):
        url = article.get("article_url")
        tickers = article.get("tickers") or []
        if not url or not tickers:
            continue
        insights = {i["ticker"]: i for i in (article.get("insights") or []) if i.get("ticker")}
        published = _parse_published_date(article.get("published_utc"))
        site = (article.get("publisher") or {}).get("name")
        for ticker in tickers:
            insight = insights.get(ticker, {})
            items.append(
                {
                    "url_hash": _hash(url, ticker),
                    "symbol": ticker,
                    "title": article.get("title") or "",
                    "site": site,
                    "url": url,
                    "published_date": published,
                    "sentiment": insight.get("sentiment"),
                    "sentiment_score": None,
                    "sentiment_reasoning": insight.get("sentiment_reasoning"),
                    "provider": "massive",
                }
            )
    return items


async def _fetch_fmp(limit: int, since: datetime | None) -> list[dict]:
    """The legacy feed has no incremental/date-filter param — `since` is
    accepted for signature symmetry with the other global fetcher but
    unused; every call just re-fetches the latest page and relies on
    `upsert_market_news`'s idempotency for the overlap.
    """
    raw = await asyncio.to_thread(fmp_get, "stock-news-sentiments-rss-feed", legacy_version="v4", page=0)
    if not isinstance(raw, list):
        return []

    items = []
    for item in raw[:limit]:
        url = item.get("url")
        symbol = item.get("symbol")
        if not url or not symbol:
            continue
        items.append(
            {
                "url_hash": _hash(url, symbol),
                "symbol": symbol,
                "title": item.get("title") or "",
                "site": item.get("site"),
                "url": url,
                "published_date": _parse_published_date(item.get("publishedDate")),
                "sentiment": item.get("sentiment"),
                "sentiment_score": item.get("sentimentScore"),
                "sentiment_reasoning": None,
                "provider": "fmp",
            }
        )
    return items


async def _fetch_newsapi(symbol: str, limit: int) -> list[dict]:
    """No native ticker tagging — `q=` is a free-text search, so every
    result is tagged with the requested `symbol` directly rather than
    parsed from the article. No sentiment of any kind.
    """
    params = {"q": symbol, "pageSize": min(limit, 100), "sortBy": "publishedAt", "apiKey": settings.news_api_key}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{settings.news_api_base_url}/everything", params=params)
        response.raise_for_status()

    items = []
    for article in response.json().get("articles", []):
        url = article.get("url")
        if not url:
            continue
        items.append(
            {
                "url_hash": _hash(url, symbol),
                "symbol": symbol,
                "title": article.get("title") or "",
                "site": (article.get("source") or {}).get("name"),
                "url": url,
                "published_date": _parse_published_date(article.get("publishedAt")),
                "sentiment": None,
                "sentiment_score": None,
                "sentiment_reasoning": None,
                "provider": "newsapi",
            }
        )
    return items


async def _fetch_gnews(symbol: str, limit: int) -> list[dict]:
    """Same free-text-search shape as NewsAPI, no ticker tagging, no
    sentiment. Free-plan delay (~12h) is accepted here as-is — this only
    runs when every higher-priority provider has already failed.
    """
    params = {"q": symbol, "max": min(limit, 10), "apikey": settings.gnews_api_key}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{settings.gnews_base_url}/search", params=params)
        response.raise_for_status()

    items = []
    for article in response.json().get("articles", []):
        url = article.get("url")
        if not url:
            continue
        items.append(
            {
                "url_hash": _hash(url, symbol),
                "symbol": symbol,
                "title": article.get("title") or "",
                "site": (article.get("source") or {}).get("name"),
                "url": url,
                "published_date": _parse_published_date(article.get("publishedAt")),
                "sentiment": None,
                "sentiment_score": None,
                "sentiment_reasoning": None,
                "provider": "gnews",
            }
        )
    return items


_GLOBAL_FETCHERS: dict[str, Callable[[int, datetime | None], Awaitable[list[dict]]]] = {
    "massive": _fetch_massive,
    "fmp": _fetch_fmp,
}
_SYMBOL_FETCHERS: dict[str, Callable[[str, int], Awaitable[list[dict]]]] = {
    "newsapi": _fetch_newsapi,
    "gnews": _fetch_gnews,
}


def _provider_order() -> list[str]:
    return [p.strip() for p in settings.market_news_provider_order.split(",") if p.strip()]


async def _fetch_global(limit: int, since: datetime | None) -> list[dict] | None:
    """`None` means every global provider failed — distinct from `[]`
    (a provider succeeded but the market was quiet), which the caller must
    NOT fall back on.
    """
    for name in _provider_order():
        fetcher = _GLOBAL_FETCHERS.get(name)
        if fetcher is None:
            continue
        try:
            return await fetcher(limit, since)
        except Exception:
            continue
    return None


async def _fetch_symbol_fallback(symbol: str, limit: int) -> list[dict]:
    for name in _provider_order():
        fetcher = _SYMBOL_FETCHERS.get(name)
        if fetcher is None:
            continue
        try:
            return await fetcher(symbol, limit)
        except Exception:
            continue
    return []


async def get_cached_market_news(
    symbol: str, *, max_age_hours: int = _DEFAULT_MAX_AGE_HOURS, fetch_limit: int = 100
) -> list[dict]:
    """Refreshes the shared global table if stale (TTL, not per-symbol),
    then returns only this `symbol`'s items published within the last
    `max_age_hours` — old general-market news isn't useful once it's more
    than about a day old.
    """
    db = SessionLocal()
    try:
        last_fetched = repository.get_market_news_last_fetched(db)
    finally:
        db.close()

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, see _parse_published_date
    is_stale = last_fetched is None or (now - last_fetched).total_seconds() >= _REFRESH_TTL_SECONDS

    if is_stale:
        fresh_items = await _fetch_global(fetch_limit, last_fetched)
        if fresh_items is None:
            # Every global provider failed this cycle — fall back to a
            # symbol-scoped provider for THIS symbol only. Deliberately does
            # NOT update MarketNewsFeedState.last_fetched_at below: it only
            # covers one symbol, so every other symbol's page should still
            # retry the global providers on its next request, not treat the
            # whole feed as freshly refreshed.
            fresh_items = await _fetch_symbol_fallback(symbol, fetch_limit)
            db = SessionLocal()
            try:
                repository.upsert_market_news(db, fresh_items)
            finally:
                db.close()
        else:
            db = SessionLocal()
            try:
                repository.upsert_market_news(db, fresh_items)
                repository.set_market_news_last_fetched(db, now)
            finally:
                db.close()

    since = now - timedelta(hours=max_age_hours)
    db = SessionLocal()
    try:
        rows = repository.get_market_news_for_symbol(db, symbol, since)
        return [
            {
                "symbol": r.symbol,
                "title": r.title,
                "site": r.site,
                "url": r.url,
                "published_date": r.published_date.isoformat() if r.published_date else None,
                "sentiment": r.sentiment,
                "sentiment_score": r.sentiment_score,
                "sentiment_reasoning": r.sentiment_reasoning,
                "provider": r.provider,
            }
            for r in rows
        ]
    finally:
        db.close()
