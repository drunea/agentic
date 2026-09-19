from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    """No auth/user flow yet, so Watchlist has no user_id FK — add once
    multi-user matters.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WatchlistItem(Base):
    """One row per (watchlist, symbol) — a symbol can appear in multiple
    watchlists. Own `added_at` per symbol, which the old single JSON
    `symbols` column on `Watchlist` couldn't carry.
    """

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_items_watchlist_symbol"),)


class CompanyAnalysis(Base):
    """One row per symbol — a live, in-place-updated snapshot, not a job
    log. `specialists` holds one entry per specialist (plus `_orchestrator`
    for the cross-signal contradictions/summary step), each independently
    timestamped and independently refreshable — see
    `orchestration.py::FRESHNESS_SECONDS` for per-specialist staleness
    thresholds and `refresh_company()` for how a partial refresh updates
    just those keys in place via a JSON-path update, not a full-row
    rewrite.

    No history is kept — an expired result is simply overwritten. Add
    historical tracking as its own explicit table/feature if ever needed,
    rather than as a side effect of this one.
    """

    __tablename__ = "company_analysis"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    # {"<specialist>": {"status": "pending"|"running"|"done"|"error",
    #                    "result": <dict|None>, "error": <str|None>,
    #                    "updated_at": "<iso datetime>|None"}, ...,
    #  "_orchestrator": {"contradictions": [...], "summary": "...", "updated_at": ...}}
    specialists: Mapped[dict] = mapped_column(JSON, default=dict)
    # None until first checked; "equity"|"etf"|"fund" after — checked once
    # (via FMP's profile isEtf/isFund flags) and cached here rather than
    # re-checked on every refresh. "etf"/"fund" makes refresh_company()
    # refuse to run any specialist for this symbol at all — see
    # orchestration.py — none of the specialists are built for funds.
    symbol_kind: Mapped[str | None] = mapped_column(String(10))
    # {"company_name", "exchange", "sector", "industry", "description"} —
    # cached the same time as `symbol_kind` (same FMP profile call), since
    # these rarely change. Stock Analysis's identity header reads this
    # instead of re-fetching FMP on every page view.
    identity: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Cross-page refresh lock: non-null means a refresh_company() background
    # task is currently in flight for this symbol (started at this UTC
    # timestamp, naive — matches this column's storage, not tz-aware like
    # the ISO strings inside `specialists`). Every "Analyze" button reads
    # this (via GET /company/{symbol}) and disables itself while set, so
    # two pages can't run overlapping refreshes for the same symbol and
    # stamp over each other's specialist entries. Set/cleared in
    # repository.try_acquire_refresh_lock()/release_refresh_lock() — see
    # orchestration.py::refresh_company for the acquire/release lifecycle.
    refresh_started_at: Mapped[datetime | None] = mapped_column(DateTime)


class SpecialistHealth(Base):
    """One row per specialist (plus `_orchestrator`): the current streak of
    consecutive failed runs, across all symbols — a streak spanning several
    runs is what distinguishes a systemic cause (expired API key, Ollama
    down) from one bad symbol. Any success resets it. `alerted` is set
    atomically when the streak first reaches the alert threshold, so one
    streak fires one alert; see `health.py`.
    """

    __tablename__ = "specialist_health"

    specialist: Mapped[str] = mapped_column(String(50), primary_key=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_symbol: Mapped[str | None] = mapped_column(String(20))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    trigger_type: Mapped[str] = mapped_column(String(20))  # "price_above" | "price_below"
    threshold_json: Mapped[str] = mapped_column(Text)  # JSON: {"price": 150.0}
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MarketNewsItem(Base):
    """A GLOBAL, symbol-independent cache of the market-wide news+sentiment
    feed (multiple providers, see `tools/market_news.py`) — the same feed
    regardless of which symbol's page is open, so it's fetched once and
    shared rather than per-symbol. Refreshed on its own TTL (see
    `tools/market_news.py::get_cached_market_news`); each page just filters
    this table by `symbol` and recency, no provider call of its own.

    One row per (article, ticker) pair, not one row per article — a single
    article can be tagged with multiple tickers (Massive), each with its own
    independent sentiment, so collapsing to one row per article would force
    picking one ticker's sentiment arbitrarily for the others. Rows are
    never inserted with a null `symbol` (an article with no ticker tag is
    simply skipped) since nothing ever queries this table without one.

    `url_hash` hashes `url + symbol`, not `url` alone — article URLs can
    exceed MySQL's indexable key-length comfortably, a fixed-length hash
    avoids that, and including `symbol` lets the same article produce one
    row per tagged ticker instead of colliding on the first insert.
    """

    __tablename__ = "market_news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(Text)
    site: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    published_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    sentiment: Mapped[str | None] = mapped_column(String(20))
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    sentiment_reasoning: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(20))  # which provider served THIS row — e.g. "massive", "fmp"

    __table_args__ = (
        Index("ix_market_news_symbol_published", "symbol", "published_date"),
        Index("ix_market_news_url_hash_symbol", "url_hash", "symbol", unique=True),
    )


class MarketNewsFeedState(Base):
    """Single-row table (id always 1) tracking when the shared global news
    feed was last successfully pulled from a GLOBAL provider (Massive/FMP —
    see `tools/market_news.py::_GLOBAL_PROVIDERS`) — one fact, stored once,
    rather than derived by aggregating a timestamp duplicated across every
    article row. A symbol-scoped fallback provider (NewsAPI/GNews) run for
    a single symbol does NOT update this, since it doesn't refresh the feed
    for every other symbol too.
    """

    __tablename__ = "market_news_feed_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime)
