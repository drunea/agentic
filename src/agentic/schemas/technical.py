from agentic.schemas.common import AgentFinding


class TechnicalReport(AgentFinding):
    symbol: str
    last_close: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    sma_20: float | None = None
    ema_20: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    trend: str
    summary: str
