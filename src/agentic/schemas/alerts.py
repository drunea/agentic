from datetime import datetime

from pydantic import BaseModel, Field

# price_above/price_below take a user-supplied `threshold` (live quote,
# checked every poll). The rest are fixed rules read from whatever's
# already cached in company_analysis (no threshold input needed) — see
# api/routers/alerts.py::_check_triggered for the exact condition each one
# evaluates.
TRIGGER_TYPES = (
    "price_above",
    "price_below",
    "rsi_oversold",
    "price_below_sma20",
    "altman_distress",
    "earnings_soon",
)
THRESHOLD_REQUIRED = {"price_above", "price_below"}


class AlertConfigIn(BaseModel):
    symbol: str
    trigger_type: str = Field(pattern="^(" + "|".join(TRIGGER_TYPES) + ")$")
    threshold: float | None = None


class AlertConfigOut(BaseModel):
    id: int
    symbol: str
    trigger_type: str
    threshold: float | None
    active: bool
    created_at: datetime
