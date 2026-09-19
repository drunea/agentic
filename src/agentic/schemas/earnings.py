from pydantic import BaseModel, Field

from agentic.schemas.common import AgentFinding


class EarningsQuarter(BaseModel):
    date: str
    eps_actual: float | None = None
    eps_estimated: float | None = None
    eps_surprise_pct: float | None = None
    revenue_actual: float | None = None
    revenue_estimated: float | None = None
    revenue_surprise_pct: float | None = None
    price_reaction_pct: float | None = Field(
        default=None,
        description="% price move from the close at-or-before this report date to the next trading day's close.",
    )


class AnalystGrade(BaseModel):
    date: str | None = None
    grading_company: str | None = None
    previous_grade: str | None = None
    new_grade: str | None = None
    action: str  # "upgrade" | "downgrade" | "maintain"


class PeerEarningsComparison(BaseModel):
    symbol: str
    is_target: bool = False
    latest_period_date: str | None = None
    latest_eps_actual: float | None = None
    eps_growth_yoy_pct: float | None = None
    latest_revenue_actual: float | None = None
    revenue_growth_yoy_pct: float | None = None


class EarningsReport(AgentFinding):
    symbol: str
    latest_period_date: str | None = None
    latest_eps_actual: float | None = None
    latest_eps_estimated: float | None = None
    latest_eps_surprise_pct: float | None = None
    latest_revenue_actual: float | None = None
    latest_revenue_estimated: float | None = None
    latest_revenue_surprise_pct: float | None = None
    eps_beat_streak: int
    quarters_analyzed: int
    next_earnings_date: str | None = None
    trend: str  # "improving" | "deteriorating" | "mixed" | "stable"
    quarterly_history: list[EarningsQuarter] = Field(
        default_factory=list, description="Most-recent-first, up to `quarters_analyzed` entries."
    )
    analyst_grades: list[AnalystGrade] = Field(default_factory=list, description="Most-recent-first.")
    upgrade_count: int = 0
    downgrade_count: int = 0
    peer_comparison: list[PeerEarningsComparison] = Field(
        default_factory=list, description="`symbol` itself first, then up to 5 direct peers."
    )
    summary: str
