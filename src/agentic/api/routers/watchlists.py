from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agentic.api.deps import get_db
from agentic.db import repository
from agentic.db.models import Watchlist, WatchlistItem

router = APIRouter()


class WatchlistItemOut(BaseModel):
    id: int
    symbol: str
    added_at: datetime


class WatchlistOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    items: list[WatchlistItemOut]


class WatchlistCreate(BaseModel):
    name: str
    symbols: list[str] = []


class WatchlistItemCreate(BaseModel):
    symbol: str


class ScreenerRow(BaseModel):
    item_id: int
    symbol: str
    added_at: datetime
    symbol_kind: str | None = None  # None (unknown/never checked) | "equity" | "etf" | "fund"
    price: float | None = None
    technical_trend: str | None = None
    technical_updated_at: str | None = None
    risk_level: str | None = None
    altman_z_score: float | None = None
    altman_zone: str | None = None
    risk_updated_at: str | None = None


def _item_to_out(row: WatchlistItem) -> WatchlistItemOut:
    return WatchlistItemOut(id=row.id, symbol=row.symbol, added_at=row.added_at)


def _to_out(db: Session, row: Watchlist) -> WatchlistOut:
    items = repository.list_watchlist_items(db, row.id)
    return WatchlistOut(
        id=row.id, name=row.name, created_at=row.created_at, items=[_item_to_out(i) for i in items]
    )


@router.get("/watchlists", response_model=list[WatchlistOut])
def get_watchlists(db: Session = Depends(get_db)) -> list[WatchlistOut]:
    return [_to_out(db, row) for row in repository.list_watchlists(db)]


@router.post("/watchlists", response_model=WatchlistOut)
def post_watchlist(body: WatchlistCreate, db: Session = Depends(get_db)) -> WatchlistOut:
    row = repository.create_watchlist(db, name=body.name, symbols=body.symbols)
    return _to_out(db, row)


@router.delete("/watchlists/{watchlist_id}")
def remove_watchlist(watchlist_id: int, db: Session = Depends(get_db)) -> dict:
    if not repository.delete_watchlist(db, watchlist_id):
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"ok": True}


@router.post("/watchlists/{watchlist_id}/items", response_model=WatchlistItemOut, status_code=201)
def post_watchlist_item(watchlist_id: int, body: WatchlistItemCreate, db: Session = Depends(get_db)) -> WatchlistItemOut:
    if db.get(Watchlist, watchlist_id) is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    row = repository.add_watchlist_item(db, watchlist_id, body.symbol)
    if row is None:
        raise HTTPException(status_code=400, detail="Symbol is required")
    return _item_to_out(row)


@router.delete("/watchlists/{watchlist_id}/items/{item_id}")
def remove_watchlist_item(watchlist_id: int, item_id: int, db: Session = Depends(get_db)) -> dict:
    if not repository.remove_watchlist_item(db, item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}


@router.get("/watchlists/{watchlist_id}/screener", response_model=list[ScreenerRow])
def get_watchlist_screener(watchlist_id: int, db: Session = Depends(get_db)) -> list[ScreenerRow]:
    """Reads whatever's already cached in `company_analysis` per symbol —
    never triggers a fresh specialist run just because a symbol is on a
    watchlist (same cache-first convention as every other page). A symbol
    never analyzed anywhere shows blank fields, not an error.
    """
    if db.get(Watchlist, watchlist_id) is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    rows = []
    for item in repository.list_watchlist_items(db, watchlist_id):
        company = repository.get_company_analysis(db, item.symbol)
        specialists = (company.specialists if company else {}) or {}
        technical = (specialists.get("technical") or {}) if specialists.get("technical") else {}
        technical_result = technical.get("result") or {}
        risk = (specialists.get("risk") or {}) if specialists.get("risk") else {}
        risk_result = risk.get("result") or {}

        rows.append(
            ScreenerRow(
                item_id=item.id,
                symbol=item.symbol,
                added_at=item.added_at,
                symbol_kind=company.symbol_kind if company else None,
                price=technical_result.get("last_close"),
                technical_trend=technical_result.get("trend"),
                technical_updated_at=technical.get("updated_at"),
                risk_level=risk_result.get("risk_level"),
                altman_z_score=risk_result.get("altman_z_score"),
                altman_zone=risk_result.get("altman_zone"),
                risk_updated_at=risk.get("updated_at"),
            )
        )
    return rows
