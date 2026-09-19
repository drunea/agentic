import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from agentic.db.models import (
    AlertConfig,
    CompanyAnalysis,
    MarketNewsFeedState,
    MarketNewsItem,
    SpecialistHealth,
    Watchlist,
    WatchlistItem,
)


def _utcnow_naive() -> datetime:
    """Naive UTC now — matches this project's DateTime columns (e.g.
    `refresh_started_at`), which store/return naive values via pymysql, not
    tz-aware ones.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def list_watchlists(db: Session) -> list[Watchlist]:
    return db.query(Watchlist).order_by(Watchlist.id).all()


def create_watchlist(db: Session, *, name: str, symbols: list[str] | None = None) -> Watchlist:
    row = Watchlist(name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    for symbol in symbols or []:
        add_watchlist_item(db, row.id, symbol)
    return row


def delete_watchlist(db: Session, watchlist_id: int) -> bool:
    row = db.get(Watchlist, watchlist_id)
    if row is None:
        return False
    db.delete(row)  # ondelete="CASCADE" on WatchlistItem.watchlist_id handles the items
    db.commit()
    return True


def list_watchlist_items(db: Session, watchlist_id: int) -> list[WatchlistItem]:
    return (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(WatchlistItem.added_at)
        .all()
    )


def add_watchlist_item(db: Session, watchlist_id: int, symbol: str) -> WatchlistItem | None:
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.symbol == symbol)
        .first()
    )
    if existing:
        return existing
    row = WatchlistItem(watchlist_id=watchlist_id, symbol=symbol)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_watchlist_item(db: Session, item_id: int) -> bool:
    row = db.get(WatchlistItem, item_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_company_analysis(db: Session, symbol: str) -> CompanyAnalysis | None:
    return db.get(CompanyAnalysis, symbol)


def get_or_create_company_analysis(db: Session, symbol: str) -> CompanyAnalysis:
    row = db.get(CompanyAnalysis, symbol)
    if row is None:
        row = CompanyAnalysis(symbol=symbol, specialists={})
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def set_symbol_kind(db: Session, symbol: str, kind: str) -> None:
    row = get_or_create_company_analysis(db, symbol)
    row.symbol_kind = kind
    db.commit()


def set_identity(db: Session, symbol: str, identity: dict) -> None:
    row = get_or_create_company_analysis(db, symbol)
    row.identity = identity
    db.commit()


# If the process running refresh_company() dies mid-task (crash, restart)
# before its finally block runs, the lock it acquired would otherwise never
# clear. Treating a lock older than this as abandoned lets a new refresh
# proceed instead of permanently freezing every "Analyze" button for that
# symbol.
_REFRESH_LOCK_STALE_SECONDS = 20 * 60


def try_acquire_refresh_lock(db: Session, symbol: str) -> bool:
    """Atomically claims the per-symbol refresh lock: only succeeds (returns
    True) if no lock is currently held, or the held lock is stale (see
    `_REFRESH_LOCK_STALE_SECONDS`). The UPDATE's WHERE clause makes this
    safe against two near-simultaneous refresh requests for the same
    symbol — only one can match a NULL/stale row and flip it, since MySQL
    row-locks the matched row for the duration of the UPDATE.
    """
    get_or_create_company_analysis(db, symbol)
    now = _utcnow_naive()
    stale_cutoff = now - timedelta(seconds=_REFRESH_LOCK_STALE_SECONDS)
    result = db.execute(
        update(CompanyAnalysis)
        .where(
            CompanyAnalysis.symbol == symbol,
            or_(CompanyAnalysis.refresh_started_at.is_(None), CompanyAnalysis.refresh_started_at < stale_cutoff),
        )
        .values(refresh_started_at=now)
    )
    db.commit()
    return result.rowcount == 1


def release_refresh_lock(db: Session, symbol: str) -> None:
    db.execute(
        update(CompanyAnalysis).where(CompanyAnalysis.symbol == symbol).values(refresh_started_at=None)
    )
    db.commit()


def is_refresh_locked(db: Session, symbol: str) -> bool:
    row = db.get(CompanyAnalysis, symbol)
    if row is None or row.refresh_started_at is None:
        return False
    return row.refresh_started_at >= _utcnow_naive() - timedelta(seconds=_REFRESH_LOCK_STALE_SECONDS)


def set_specialist_entry(db: Session, symbol: str, specialist: str, entry: dict) -> None:
    """Overwrites `specialists[specialist]` in place — the one path every
    status transition (pending/running/done/error) goes through, so a
    partial refresh only ever touches the keys it's responsible for.
    SQLAlchemy doesn't auto-detect in-place dict mutation on a JSON column,
    hence the explicit `flag_modified`.
    """
    row = get_or_create_company_analysis(db, symbol)
    row.specialists[specialist] = entry
    flag_modified(row, "specialists")
    db.commit()


def record_specialist_failure(db: Session, specialist: str, symbol: str, error: str) -> int:
    """Increments the specialist's failure streak (creating its row on first
    failure) and returns the new streak length. The increment happens inside
    MySQL, so concurrent failures of the same specialist (two symbols
    refreshing at once) never lose a count.
    """
    now = _utcnow_naive()
    stmt = mysql_insert(SpecialistHealth).values(
        specialist=specialist,
        consecutive_failures=1,
        alerted=False,
        last_error=error,
        last_error_symbol=symbol,
        last_failure_at=now,
    )
    stmt = stmt.on_duplicate_key_update(
        consecutive_failures=SpecialistHealth.consecutive_failures + 1,
        last_error=stmt.inserted.last_error,
        last_error_symbol=stmt.inserted.last_error_symbol,
        last_failure_at=stmt.inserted.last_failure_at,
    )
    db.execute(stmt)
    db.commit()
    return db.execute(
        select(SpecialistHealth.consecutive_failures).where(SpecialistHealth.specialist == specialist)
    ).scalar_one()


def record_specialist_success(db: Session, specialist: str) -> bool:
    """Ends any failure streak. Returns True if that streak had already
    triggered an alert (so the caller can announce the recovery).
    """
    was_alerted = bool(
        db.execute(select(SpecialistHealth.alerted).where(SpecialistHealth.specialist == specialist)).scalar()
    )
    now = _utcnow_naive()
    stmt = mysql_insert(SpecialistHealth).values(
        specialist=specialist, consecutive_failures=0, alerted=False, last_success_at=now
    )
    stmt = stmt.on_duplicate_key_update(
        consecutive_failures=0, alerted=False, last_success_at=stmt.inserted.last_success_at
    )
    db.execute(stmt)
    db.commit()
    return was_alerted


def claim_specialist_alert(db: Session, specialist: str, threshold: int) -> bool:
    """Atomically marks the current streak as alerted; True only for the one
    caller that flipped it, so a streak fires exactly one alert even when
    several failures land at the same moment.
    """
    result = db.execute(
        update(SpecialistHealth)
        .where(
            SpecialistHealth.specialist == specialist,
            SpecialistHealth.consecutive_failures >= threshold,
            SpecialistHealth.alerted.is_(False),
        )
        .values(alerted=True)
    )
    db.commit()
    return result.rowcount == 1


def list_specialist_health(db: Session) -> list[SpecialistHealth]:
    return db.query(SpecialistHealth).order_by(SpecialistHealth.specialist).all()


def list_alert_configs(db: Session, *, active_only: bool = True) -> list[AlertConfig]:
    query = db.query(AlertConfig)
    if active_only:
        query = query.filter(AlertConfig.active.is_(True))
    return query.order_by(AlertConfig.id).all()


def create_alert_config(
    db: Session, *, symbol: str, trigger_type: str, threshold: float | None
) -> AlertConfig:
    row = AlertConfig(
        symbol=symbol,
        trigger_type=trigger_type,
        threshold_json=json.dumps({"price": threshold} if threshold is not None else {}),
        active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_alert_config(db: Session, alert_id: int) -> bool:
    row = db.get(AlertConfig, alert_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_market_news_last_fetched(db: Session) -> datetime | None:
    """Drives the global feed's own TTL (see
    `tools/market_news.py::get_cached_market_news`) — independent of any
    single symbol. A single row (id=1), not derived by aggregating over the
    article table, which would mean writing the same timestamp onto every
    article row per refresh just to read it back as one value.
    """
    row = db.get(MarketNewsFeedState, 1)
    return row.last_fetched_at if row else None


def set_market_news_last_fetched(db: Session, when: datetime) -> None:
    row = db.get(MarketNewsFeedState, 1)
    if row is None:
        db.add(MarketNewsFeedState(id=1, last_fetched_at=when))
    else:
        row.last_fetched_at = when
    db.commit()


def upsert_market_news(db: Session, items: list[dict]) -> None:
    """`items`: dicts with url_hash/symbol/title/site/url/published_date/
    sentiment/sentiment_score/sentiment_reasoning/provider. Idempotent on
    `(url_hash, symbol)` — re-fetching the same article+ticker across
    refreshes (a provider's feed naturally overlaps refresh to refresh) is a
    no-op via MySQL's `INSERT ... ON DUPLICATE KEY UPDATE`, not a duplicate
    row or a crash.
    """
    if not items:
        return
    stmt = mysql_insert(MarketNewsItem).values(items)
    stmt = stmt.on_duplicate_key_update(
        title=stmt.inserted.title,
        sentiment=stmt.inserted.sentiment,
        sentiment_score=stmt.inserted.sentiment_score,
        sentiment_reasoning=stmt.inserted.sentiment_reasoning,
        provider=stmt.inserted.provider,
    )
    db.execute(stmt)
    db.commit()


def get_market_news_for_symbol(db: Session, symbol: str, since: datetime) -> list[MarketNewsItem]:
    return (
        db.query(MarketNewsItem)
        .filter(MarketNewsItem.symbol == symbol, MarketNewsItem.published_date >= since)
        .order_by(MarketNewsItem.published_date.desc())
        .all()
    )
