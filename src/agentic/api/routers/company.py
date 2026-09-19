"""One symbol, one live snapshot. `GET` is always instant (just reads the
current row); `POST /refresh` kicks off only the specialists the caller
explicitly asks for, in the background, updating the same row in place as
each finishes.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from agentic.api.deps import get_db
from agentic.db import repository
from agentic.llm import get_model_info
from agentic.orchestration import SPECIALISTS, is_expired, refresh_company
from agentic.schemas.company import CompanyAnalysisView, OrchestratorView, RefreshRequest, SpecialistView

router = APIRouter()


@router.get("/specialists-info")
def get_specialists_info() -> dict:
    """Static, per-specialist config (which model, if any, runs it) — not
    per-symbol data, safe to call without a symbol and to cache client-side.
    """
    names = list(SPECIALISTS) + ["orchestrator"]
    return {name: get_model_info(name) for name in names}


@router.get("/company/{symbol}", response_model=CompanyAnalysisView)
def get_company(symbol: str, db: Session = Depends(get_db)) -> CompanyAnalysisView:
    row = repository.get_company_analysis(db, symbol)
    data = row.specialists if row else {}

    specialists_out: dict[str, SpecialistView] = {}
    for name in SPECIALISTS:
        entry = data.get(name)
        specialists_out[name] = SpecialistView(
            status=(entry or {}).get("status", "never_run"),
            result=(entry or {}).get("result"),
            error=(entry or {}).get("error"),
            updated_at=(entry or {}).get("updated_at"),
            is_expired=is_expired(entry, name),
        )

    orchestrator_entry = data.get("_orchestrator") or {}
    # Old entries (written before `status` existed) have no such key —
    # inferred from `summary` being present instead, rather than treating
    # them as "never run" when they actually completed previously.
    orchestrator_status = orchestrator_entry.get("status") or (
        "done" if orchestrator_entry.get("summary") else "never_run"
    )
    orchestrator_out = OrchestratorView(
        status=orchestrator_status,
        contradictions=orchestrator_entry.get("contradictions", []),
        summary=orchestrator_entry.get("summary"),
        error=orchestrator_entry.get("error"),
        updated_at=orchestrator_entry.get("updated_at"),
    )

    return CompanyAnalysisView(
        symbol=symbol,
        specialists=specialists_out,
        orchestrator=orchestrator_out,
        symbol_kind=row.symbol_kind if row else None,
        identity=row.identity if row else None,
        is_refreshing=repository.is_refresh_locked(db, symbol),
    )


@router.post("/company/{symbol}/refresh", status_code=202)
async def refresh(
    symbol: str, request: RefreshRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> dict:
    # Acquired here, synchronously, before the background task is even
    # scheduled — a second POST for the same symbol arriving moments later
    # (another page's "Analyze" button) must see the lock immediately, not
    # only once the background task itself gets around to starting.
    if not repository.try_acquire_refresh_lock(db, symbol):
        raise HTTPException(status_code=409, detail=f"A refresh is already running for {symbol}")
    valid = [s for s in request.specialists if s in SPECIALISTS]
    affo_iterations = max(1, min(3, request.affo_iterations))
    background_tasks.add_task(refresh_company, symbol, valid, affo_iterations)
    return {"status": "started", "specialists": valid}
