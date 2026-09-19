from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agentic.api.deps import get_db
from agentic.db import repository
from agentic.health import FAILURE_ALERT_THRESHOLD
from agentic.schemas.health import SpecialistHealthView

router = APIRouter()


@router.get("/health/specialists", response_model=list[SpecialistHealthView])
def get_specialists_health(db: Session = Depends(get_db)) -> list[SpecialistHealthView]:
    """Per-specialist failure streaks, across all symbols — the aggregated
    view of what `run_specialist` otherwise only records per symbol.
    """
    return [
        SpecialistHealthView(
            specialist=row.specialist,
            consecutive_failures=row.consecutive_failures,
            alerting=row.consecutive_failures >= FAILURE_ALERT_THRESHOLD,
            last_error=row.last_error,
            last_error_symbol=row.last_error_symbol,
            last_failure_at=row.last_failure_at.isoformat() if row.last_failure_at else None,
            last_success_at=row.last_success_at.isoformat() if row.last_success_at else None,
        )
        for row in repository.list_specialist_health(db)
    ]
