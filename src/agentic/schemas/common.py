from pydantic import BaseModel, Field


class FilingCitation(BaseModel):
    """An LLM-written insight tied to the SEC filing excerpt it was based
    on. `filing_type`/`filing_date`/`excerpt` are copied from the retrieved
    chunk by Python, never transcribed by the LLM — only `insight` is its own.
    """

    insight: str
    filing_type: str
    filing_date: str
    excerpt: str


class AgentFinding(BaseModel):
    """Base shape every specialist report carries, so the orchestrator can
    compare/aggregate findings uniformly regardless of which agent produced them."""

    confidence: float = Field(
        ge=0,
        le=1,
        description="0-1 confidence in this finding, based on data completeness/quality.",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Known limitations or missing data affecting this finding.",
    )
    data_source: str = Field(
        default="",
        description="Which provider actually served this specialist's underlying data — e.g. 'fmp', 'yfinance', 'roic'. Empty if not tracked for this specialist.",
    )
