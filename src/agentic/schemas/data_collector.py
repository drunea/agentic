from agentic.schemas.common import AgentFinding


class DataCollectorReport(AgentFinding):
    symbol: str
    price: float | None = None
    previous_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    year_high: float | None = None
    year_low: float | None = None
    volume: float | None = None
    market_cap: float | None = None
    history_points: int
    summary: str
