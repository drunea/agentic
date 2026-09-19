"""Income/Balance/Cash Flow statements + Capital Efficiency — pure Python,
no LLM (same category as technical/risk/performance). `provider` is unused
(FMP is called directly, like earnings_analyst) but kept in the signature so
this fits `orchestration.SpecialistFn` without an adapter.
"""

import asyncio

from agentic.data.base import DataProvider
from agentic.schemas.financial_statements import FinancialStatementsReport
from agentic.tools.capital_efficiency import get_capital_efficiency
from agentic.tools.capital_return import get_capital_return_policy
from agentic.tools.financial_statements import get_statement_table, recommend_view
from agentic.tools.segmentation import get_geographic_segmentation, get_product_segmentation


def _latest_historical_date(fiscal_years: list[dict]) -> str | None:
    historical_dates = [c["date"] for c in fiscal_years if not c.get("is_estimate")]
    return max(historical_dates) if historical_dates else None


async def analyze_financial_statements(provider: DataProvider, symbol: str) -> FinancialStatementsReport:
    view = await recommend_view(symbol)

    (
        income_annual,
        balance_annual,
        cash_annual,
        income_quarter,
        balance_quarter,
        cash_quarter,
        capital_efficiency,
        capital_return,
        product_segmentation,
        geographic_segmentation,
    ) = await asyncio.gather(
        get_statement_table(symbol, "income", view, "annual"),
        get_statement_table(symbol, "balance", view, "annual"),
        get_statement_table(symbol, "cash", view, "annual"),
        get_statement_table(symbol, "income", view, "quarter"),
        get_statement_table(symbol, "balance", view, "quarter"),
        get_statement_table(symbol, "cash", view, "quarter"),
        get_capital_efficiency(symbol),
        get_capital_return_policy(symbol),
        get_product_segmentation(symbol),
        get_geographic_segmentation(symbol),
    )

    latest_annual = _latest_historical_date(income_annual["fiscal_years"])
    latest_quarterly = _latest_historical_date(income_quarter["fiscal_years"])

    caveats = []
    if latest_annual is None:
        caveats.append("No annual statement data available")
    if latest_quarterly is None:
        caveats.append("No quarterly statement data available")
    confidence = max(0.0, round(1.0 - 0.3 * len(caveats), 2))

    summary = (
        f"{symbol}: {view} financial statements — latest annual report "
        f"{latest_annual or 'n/a'}, latest quarterly report {latest_quarterly or 'n/a'}."
    )

    return FinancialStatementsReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        data_source="fmp",  # always FMP direct, no fallback chain — see module docstring
        view=view,
        latest_annual_report_date=latest_annual,
        latest_quarterly_report_date=latest_quarterly,
        income_annual=income_annual,
        balance_annual=balance_annual,
        cash_annual=cash_annual,
        income_quarter=income_quarter,
        balance_quarter=balance_quarter,
        cash_quarter=cash_quarter,
        capital_efficiency=capital_efficiency,
        capital_return=capital_return,
        product_segmentation=product_segmentation,
        geographic_segmentation=geographic_segmentation,
        summary=summary,
    )
