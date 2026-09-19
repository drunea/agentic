"""Systemic-failure detection for specialists. `run_specialist` catches every
exception and stores it as `status: "error"` on that one symbol's row — good
for the page showing it, but nothing noticed when the SAME specialist kept
failing run after run (expired API key, Ollama down). This tracks each
specialist's streak of consecutive failed runs (see `SpecialistHealth`) and,
when a streak reaches `FAILURE_ALERT_THRESHOLD`, raises one alert: an ERROR
log line plus, if `ALERT_WEBHOOK_URL` is set, a webhook POST. A later success
ends the streak and, if it had alerted, announces the recovery.

Recording must never break the run being recorded, so every entry point here
swallows (and logs) its own failures.
"""

import asyncio
import logging

import httpx

from agentic.config import settings
from agentic.db import repository
from agentic.db.session import SessionLocal

logger = logging.getLogger(__name__)

FAILURE_ALERT_THRESHOLD = 3
_ERROR_MAX_CHARS = 300


async def record_success(specialist: str) -> None:
    try:
        db = SessionLocal()
        try:
            recovered = repository.record_specialist_success(db, specialist)
        finally:
            db.close()
        if recovered:
            await _notify(f"Specialist '{specialist}' recovered: it succeeded again after a failure streak.", logging.INFO)
    except Exception:  # noqa: BLE001
        logger.exception("Could not record success for specialist '%s'", specialist)


async def record_failure(specialist: str, symbol: str, error: str) -> None:
    try:
        error = error[:_ERROR_MAX_CHARS]
        db = SessionLocal()
        try:
            streak = repository.record_specialist_failure(db, specialist, symbol, error)
            should_alert = streak >= FAILURE_ALERT_THRESHOLD and repository.claim_specialist_alert(
                db, specialist, FAILURE_ALERT_THRESHOLD
            )
        finally:
            db.close()
        if should_alert:
            await _notify(
                f"Specialist '{specialist}' has failed {streak} runs in a row (latest on {symbol}): {error}",
                logging.ERROR,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Could not record failure for specialist '%s'", specialist)


async def _notify(message: str, level: int) -> None:
    logger.log(level, message)
    if not settings.alert_webhook_url:
        return
    try:
        response = await asyncio.to_thread(
            httpx.post, settings.alert_webhook_url, json={"text": message}, timeout=10
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alert webhook delivery failed: %s", exc)
