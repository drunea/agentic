from pydantic import BaseModel


class SpecialistHealthView(BaseModel):
    specialist: str
    consecutive_failures: int
    # True once the failure streak has reached the alert threshold and hasn't
    # been ended by a success since.
    alerting: bool
    last_error: str | None = None
    last_error_symbol: str | None = None
    last_failure_at: str | None = None
    last_success_at: str | None = None
