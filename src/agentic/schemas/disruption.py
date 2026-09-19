from pydantic import Field

from agentic.schemas.common import AgentFinding, FilingCitation


class DisruptionReport(AgentFinding):
    symbol: str
    rd_to_revenue_pct: float | None = None
    revenue_growth_pct: float | None = None
    disruption_posture: str  # "disruptor" | "vulnerable" | "neutral"
    disruption_risk_score: float = Field(
        ge=0, le=1, description="Risk of this company being disrupted by others (not its own R&D output)."
    )
    opportunities: list[str] = Field(default_factory=list)
    threats: list[str] = Field(default_factory=list)
    filing_insights: list[FilingCitation] = Field(
        default_factory=list,
        description="Competition/technology-risk notes grounded in the company's own 10-K, each with its source excerpt.",
    )
    summary: str
