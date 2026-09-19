from pydantic import Field

from agentic.schemas.common import AgentFinding


class RiskReport(AgentFinding):
    symbol: str
    # --- Market Risk (price volatility) ---
    var_pct: float | None = None
    cvar_pct: float | None = None
    confidence_level: float
    horizon_days: int
    rate_environment_series: str
    rate_environment_latest: float | None = None
    rate_environment_previous: float | None = None
    risk_level: str

    # --- Balance Sheet & Solvency (insolvency risk) ---
    altman_z_score: float | None = None
    altman_zone: str | None = None  # "safe" | "grey" | "distress"
    altman_components: dict[str, float | None] = Field(default_factory=dict)
    piotroski_f_score: int | None = None
    piotroski_criteria_determined: int = 0
    piotroski_criteria: dict[str, bool | None] = Field(default_factory=dict)
    net_debt_to_ebitda: float | None = None
    interest_coverage_ratio: float | None = None
    credit_risk_period_date: str | None = None

    summary: str
