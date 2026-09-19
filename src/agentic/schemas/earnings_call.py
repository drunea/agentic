from pydantic import BaseModel, Field

from agentic.schemas.common import AgentFinding


class EvasiveStatement(BaseModel):
    question: str | None = Field(default=None, description="The analyst's question, if identifiable.")
    response_excerpt: str = Field(description="Short excerpt/paraphrase of management's response.")
    why_evasive: str = Field(description="What makes this evasive — deflection, non-answer, vague hedging, etc.")


class EarningsCallReport(AgentFinding):
    """AFFO pattern reused deliberately: symbol-specific, filing-cadence
    freshness (quarterly, judged against `call_date` — see
    orchestration.py's custom expiry), single Gemini call over the full
    transcript text (a real transcript runs ~12k tokens, too close to
    Ollama's 16k context ceiling for comfort).
    """

    symbol: str
    quarter: int
    year: int
    call_date: str | None = None
    management_tone: str = Field(
        description="Overall tone of leadership on the call — e.g. confident, cautious, defensive, upbeat."
    )
    key_topics: list[str] = Field(default_factory=list)
    evasive_statements: list[EvasiveStatement] = Field(default_factory=list)
    summary: str
