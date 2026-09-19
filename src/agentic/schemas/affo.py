from pydantic import BaseModel, Field

from agentic.schemas.common import AgentFinding


class AFFOYearData(BaseModel):
    fiscal_year: int
    net_income: float | None = None
    ffo: float | None = None
    ffo_per_share: float | None = None
    affo: float | None = None
    affo_per_share: float | None = None
    diluted_shares: float | None = None


class AFFOReport(AgentFinding):
    """REIT-only. Non-REITs get `is_reit=False` and an empty
    `historical_data` — no SEC download, no LLM call, cheap to refresh.

    `latest_annual_report_date` drives this specialist's freshness (see
    orchestration.py's custom expiry for financial_statements, the same
    pattern) — independent of whether the LLM extraction actually found
    every field, so a partial extraction doesn't get silently treated as
    permanently fresh.
    """

    symbol: str
    is_reit: bool
    latest_annual_report_date: str | None = None
    metric_name_used_by_company: str | None = Field(
        default=None, description="AFFO, FAD, CAD, etc. — whatever term the company itself uses."
    )
    historical_data: list[AFFOYearData] = Field(default_factory=list)
    processed_filing_dates: list[str] = Field(
        default_factory=list,
        description="10-K filed-dates already extracted (accumulated across refreshes) — lets the "
        "next refresh request the filing just before the earliest one already processed, instead "
        "of re-fetching the same latest 10-K every time.",
    )
    years_per_table: int | None = Field(
        default=None,
        description="Number of comparative fiscal years this company's own 10-K reconciliation "
        "table actually contains, learned from the first successful extraction and reused on "
        "every later refresh instead of assuming a fixed number. Drives how many filings a "
        "backward-walk skips to avoid re-extracting years already on file.",
    )
    summary: str
