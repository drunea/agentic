from pydantic import BaseModel, Field

from agentic.schemas.common import AgentFinding, FilingCitation


class DCFResult(BaseModel):
    """Simplified single-stage DCF. 3-scenario + WACC sensitivity comes later."""

    fair_value_per_share: float | None
    wacc: float
    growth_rate: float


class ValuationReport(AgentFinding):
    symbol: str
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    roe: float | None = None
    fcf_per_share: float | None = None
    dcf: DCFResult
    peers: list[str] = Field(default_factory=list)
    filing_citations: list[FilingCitation] = Field(
        default_factory=list,
        description="Interpretive notes grounded in SEC filing excerpts, each with the excerpt it came from.",
    )
    summary: str
