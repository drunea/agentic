"""Alert CRUD + a WebSocket that pushes a message the first time each active
alert triggers. No broker/Redis (per the project's locked-in decisions) —
each connection runs its own polling loop.

Two trigger families, checked differently:
- `price_above`/`price_below` — a live quote every poll (the original
  design), since there's no "price" specialist result to read instead.
- Everything else (`rsi_oversold`, `price_below_sma20`, `altman_distress`,
  `earnings_soon`) — read from whatever's already cached in
  `company_analysis` (Technical/Risk/Earnings specialists), never a fresh
  specialist run — same cache-first convention as every other page. A
  symbol whose relevant specialist has never run just never triggers,
  rather than forcing one.
"""

import asyncio
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from agentic.api.deps import get_db
from agentic.data.chain import ProviderChain
from agentic.db import repository
from agentic.db.models import AlertConfig
from agentic.db.session import SessionLocal
from agentic.schemas.alerts import THRESHOLD_REQUIRED, AlertConfigIn, AlertConfigOut

router = APIRouter()

_POLL_INTERVAL_SECONDS = 30
_RSI_OVERSOLD_THRESHOLD = 30
_ALTMAN_DISTRESS_THRESHOLD = 2.99
_EARNINGS_SOON_DAYS = 5


def _to_out(row: AlertConfig) -> AlertConfigOut:
    threshold = json.loads(row.threshold_json).get("price")
    return AlertConfigOut(
        id=row.id,
        symbol=row.symbol,
        trigger_type=row.trigger_type,
        threshold=threshold,
        active=row.active,
        created_at=row.created_at,
    )


@router.get("/alerts", response_model=list[AlertConfigOut])
def list_alerts(db: Session = Depends(get_db)) -> list[AlertConfigOut]:
    return [_to_out(row) for row in repository.list_alert_configs(db, active_only=False)]


@router.post("/alerts", response_model=AlertConfigOut, status_code=201)
def create_alert(alert: AlertConfigIn, db: Session = Depends(get_db)) -> AlertConfigOut:
    if alert.trigger_type in THRESHOLD_REQUIRED and alert.threshold is None:
        raise HTTPException(status_code=400, detail=f"{alert.trigger_type} requires a threshold")
    row = repository.create_alert_config(
        db,
        symbol=alert.symbol.strip().upper(),
        trigger_type=alert.trigger_type,
        threshold=alert.threshold,
    )
    return _to_out(row)


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    if not repository.delete_alert_config(db, alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"deleted": True}


def _check_triggered(config: AlertConfig, quote: dict | None, company) -> tuple[bool, dict]:
    specialists = (company.specialists if company else {}) or {}

    if config.trigger_type in ("price_above", "price_below"):
        threshold = json.loads(config.threshold_json).get("price")
        price = quote.get("price") if quote else None
        if price is None or threshold is None:
            return False, {}
        triggered = (price >= threshold) if config.trigger_type == "price_above" else (price <= threshold)
        return triggered, {"price": price, "threshold": threshold}

    technical = (specialists.get("technical") or {}).get("result") or {}
    if config.trigger_type == "rsi_oversold":
        rsi = technical.get("rsi_14")
        if rsi is None:
            return False, {}
        return rsi < _RSI_OVERSOLD_THRESHOLD, {"rsi_14": rsi}

    if config.trigger_type == "price_below_sma20":
        price, sma20 = technical.get("last_close"), technical.get("sma_20")
        if price is None or sma20 is None:
            return False, {}
        return price < sma20, {"last_close": price, "sma_20": sma20}

    if config.trigger_type == "altman_distress":
        risk = (specialists.get("risk") or {}).get("result") or {}
        z_score = risk.get("altman_z_score")
        if z_score is None:
            return False, {}
        return z_score < _ALTMAN_DISTRESS_THRESHOLD, {"altman_z_score": z_score}

    if config.trigger_type == "earnings_soon":
        earnings = (specialists.get("earnings") or {}).get("result") or {}
        next_date = earnings.get("next_earnings_date")
        if not next_date:
            return False, {}
        days_until = (date.fromisoformat(next_date) - date.today()).days
        return 0 <= days_until <= _EARNINGS_SOON_DAYS, {"next_earnings_date": next_date, "days_until": days_until}

    return False, {}


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    await websocket.accept()
    provider = ProviderChain()
    already_triggered: set[int] = set()
    try:
        while True:
            db = SessionLocal()
            try:
                configs = repository.list_alert_configs(db, active_only=True)
                pending = [c for c in configs if c.id not in already_triggered]
                symbols = {c.symbol for c in pending}
                companies = {symbol: repository.get_company_analysis(db, symbol) for symbol in symbols}
            finally:
                db.close()

            for config in pending:
                quote = None
                if config.trigger_type in ("price_above", "price_below"):
                    try:
                        quote = await provider.get_quote(config.symbol)
                    except Exception:  # noqa: BLE001 - one bad symbol shouldn't kill the loop
                        continue

                triggered, detail = _check_triggered(config, quote, companies.get(config.symbol))
                if triggered:
                    already_triggered.add(config.id)
                    await websocket.send_json(
                        {
                            "alert_id": config.id,
                            "symbol": config.symbol,
                            "trigger_type": config.trigger_type,
                            **detail,
                        }
                    )

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        pass
