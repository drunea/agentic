from agentic.schemas.common import AgentFinding


class FinancialStatementsReport(AgentFinding):
    """Income/Balance/Cash Flow tables (annual + quarterly), Capital
    Efficiency (ROIC/WACC/EVA/DuPont), Capital Return Policy (dividend
    history by fiscal year, payout ratios, share count context), and
    revenue Segmentation (by product and by geography) — all computed from
    FMP data. No LLM involved — pure Python/FMP, same as
    technical/risk/performance.

    `latest_annual_report_date`/`latest_quarterly_report_date` drive this
    specialist's freshness instead of `updated_at`: staleness is judged
    against when the company itself last actually reported, not against
    when we last fetched (see orchestration.py's custom expiry for this
    specialist).
    """

    symbol: str
    view: str  # "default" | "banks" — from financial_statements.recommend_view()
    latest_annual_report_date: str | None = None
    latest_quarterly_report_date: str | None = None
    income_annual: dict
    balance_annual: dict
    cash_annual: dict
    income_quarter: dict
    balance_quarter: dict
    cash_quarter: dict
    capital_efficiency: dict
    capital_return: dict
    product_segmentation: dict
    geographic_segmentation: dict
    summary: str
