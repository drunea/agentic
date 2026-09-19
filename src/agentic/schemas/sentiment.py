from pydantic import BaseModel, Field

from agentic.schemas.common import AgentFinding


class Headline(BaseModel):
    title: str
    url: str | None = None
    site: str | None = None


class SentimentReport(AgentFinding):
    symbol: str
    average_score: float | None = None
    article_count: int
    tone: str
    headlines: list[Headline] = Field(default_factory=list)
    summary: str
