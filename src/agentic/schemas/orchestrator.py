from pydantic import BaseModel, Field

from agentic.schemas.data_collector import DataCollectorReport
from agentic.schemas.disruption import DisruptionReport
from agentic.schemas.earnings import EarningsReport
from agentic.schemas.performance import PerformanceReport
from agentic.schemas.risk import RiskReport
from agentic.schemas.sentiment import SentimentReport
from agentic.schemas.technical import TechnicalReport
from agentic.schemas.valuation import ValuationReport


class Contradiction(BaseModel):
    description: str
    involved_agents: list[str]


class OrchestratorReport(BaseModel):
    """Explicit per-specialist fields (not a generic `findings: list[AgentFinding]`)
    — simpler than a discriminated union while there are only a handful of
    specialists.
    """

    symbol: str
    data: DataCollectorReport
    valuation: ValuationReport
    technical: TechnicalReport
    sentiment: SentimentReport
    risk: RiskReport
    performance: PerformanceReport
    disruption: DisruptionReport
    earnings: EarningsReport
    contradictions: list[Contradiction] = Field(default_factory=list)
    summary: str
