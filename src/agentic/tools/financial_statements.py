"""Standardized historical financial statements — Fundamental Deep Dive's
first section. Table structure and bank-view heuristic ported from a proven
prior design rather than invented here. Several fields (EBIT, EBITDA,
Operating Income, Net Debt, etc.) are deliberately *recomputed* rather than
trusted from FMP's own equivalent fields — FMP sometimes gets these wrong.
Pure Python/FMP direct sourcing, zero LLM.

Banks (and bank-like companies FMP doesn't label as such, e.g. AXP/MS) get
a structurally different set of rows — deposits/loans dominate their
balance sheet and net interest income their income statement, which the
default rows don't represent meaningfully. See `recommend_view()`.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from agentic.data.fmp_client import fmp_get
from agentic.tools.company_profile import get_company_profile

Period = dict

_BANK_INDUSTRIES = {"Banks - Regional", "Banks - Diversified"}
_BANK_INTEREST_INCOME_THRESHOLD = 0.20


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def growth(p: Period, prev_p: Period | None, key: str) -> float | None:
    if prev_p is None:
        return None
    cur, prev = p.get(key), prev_p.get(key)
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev)


def _neg(value: float | None) -> float | None:
    return -value if value is not None else None


def _sum(*values: float | None) -> float | None:
    if any(v is None for v in values):
        return None
    return sum(values)


def _sub(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


# ---------------------------------------------------------------------------
# Income statement helpers
# ---------------------------------------------------------------------------


def _sga_subsplit(p: Period, key: str) -> float | None:
    """FMP reports a literal 0 (not null) for `sellingAndMarketingExpenses`/
    `generalAndAdministrativeExpenses` in years a company didn't break SG&A
    out that way — even though `sellingGeneralAndAdministrativeExpenses`
    (the parent total) is populated. Verified live: even AAPL has this for
    FY2023 (both sub-fields 0, SG&A total $24.9B), while FY2024/2025 have
    the real split. Showing "0.0" there would misleadingly read as "zero
    marketing spend" instead of "not broken out this year" — blank instead.
    """
    value = p.get(key)
    parent = p.get("sellingGeneralAndAdministrativeExpenses")
    if value == 0 and parent:
        return None
    return value


def ebit(p: Period) -> float | None:
    """EBT + Net Interest Expense — recomputed, not FMP's raw `ebit` field."""
    return _sum(p.get("incomeBeforeTax"), p.get("interestExpense"), _neg(p.get("interestIncome")))


def ebitda(p: Period) -> float | None:
    """EBIT + D&A — recomputed, not FMP's raw `ebitda` field."""
    return _sum(ebit(p), p.get("depreciationAndAmortization"))


def operating_income(p: Period) -> float | None:
    """Gross Profit − Operating Expenses — recomputed, not FMP's raw `operatingIncome` field."""
    return _sub(p.get("grossProfit"), p.get("operatingExpenses"))


def net_interest_expense(p: Period) -> float | None:
    return _sub(p.get("interestExpense"), p.get("interestIncome"))


def net_interest_income(p: Period) -> float | None:
    return _sub(p.get("interestIncome"), p.get("interestExpense"))


def non_interest_income(p: Period) -> float | None:
    return _sub(p.get("revenue"), p.get("interestIncome"))


def total_bank_revenue(p: Period) -> float | None:
    """FMP's `revenue` field is, for banks, gross interest income + non-interest
    income (before subtracting interest expense) — not the Yahoo/GuruFocus
    convention of Net Interest Income + Non-Interest Income. Recomputed here.
    """
    return _sum(net_interest_income(p), non_interest_income(p))


def provision_for_credit_losses(p: Period) -> float | None:
    """FMP has no dedicated field for banks — estimated as Cost of Revenue
    (interest + provisions) minus Interest Expense.
    """
    return _sub(p.get("costOfRevenue"), p.get("interestExpense"))


def minority_interest_income(p: Period) -> float | None:
    return _sub(p.get("netIncome"), p.get("netIncomeFromContinuingOperations"))


# ---------------------------------------------------------------------------
# Balance sheet helpers
# ---------------------------------------------------------------------------


def total_financial_debt(p: Period) -> float | None:
    return _sum(
        p.get("shortTermDebt"),
        p.get("capitalLeaseObligationsCurrent"),
        p.get("longTermDebt"),
        p.get("capitalLeaseObligationsNonCurrent"),
    )


def net_debt_computed(p: Period) -> float | None:
    """Total Financial Debt − Cash & Short-Term Investments — differs from
    FMP's own `netDebt` field, which only subtracts Cash & Equivalents.
    """
    return _sub(total_financial_debt(p), p.get("cashAndShortTermInvestments"))


# ---------------------------------------------------------------------------
# Row definitions
# ---------------------------------------------------------------------------


@dataclass
class Row:
    label: str
    key: str | None = None
    calculation: Callable[[Period, Period | None], float | None] | None = None
    is_bold: bool = False
    is_subheader: bool = False
    indent: int = 0
    format_type: str = "millions"  # "millions" | "percentage" | "raw"
    tooltip: str | None = None
    # Key on a normalized analyst-estimates period (see get_income_statement_estimates)
    # this row can be filled from — only 5 rows have a forward estimate at all
    # (Revenue, EBITDA, EBIT, Net Income, EPS); every other row is deliberately
    # left blank for estimate columns rather than guessed.
    estimate_key: str | None = None

    def value(self, p: Period, prev_p: Period | None, is_estimate: bool = False) -> float | None:
        if is_estimate:
            return p.get(self.estimate_key) if self.estimate_key is not None else None
        if self.calculation is not None:
            return self.calculation(p, prev_p)
        if self.key is not None:
            return p.get(self.key)
        return None


INCOME_ROWS: list[Row] = [
    Row("Total Revenues", key="revenue", is_bold=True, estimate_key="revenue"),
    Row("Revenue Growth", calculation=lambda p, pv: growth(p, pv, "revenue"), format_type="percentage"),
    Row("Cost of Revenues", key="costOfRevenue"),
    Row("Gross Profit", key="grossProfit", is_bold=True),
    Row("Gross Profit Margin", calculation=lambda p, pv: safe_div(p.get("grossProfit"), p.get("revenue")), format_type="percentage"),
    Row("Operating Expenses", key="operatingExpenses", is_bold=True, is_subheader=True),
    Row("Selling, General and Admin Expenses", key="sellingGeneralAndAdministrativeExpenses", indent=1),
    Row("Marketing Expenses", calculation=lambda p, pv: _sga_subsplit(p, "sellingAndMarketingExpenses"), indent=2),
    Row("General & Administrative Expenses", calculation=lambda p, pv: _sga_subsplit(p, "generalAndAdministrativeExpenses"), indent=2),
    Row("Research and Development Expenses", key="researchAndDevelopmentExpenses", indent=1),
    Row("Other Expenses", key="otherExpenses", indent=1),
    Row("Operating Income", calculation=lambda p, pv: operating_income(p), is_bold=True, tooltip="Gross Profit − Operating Expenses (computed, not FMP's raw field)"),
    Row("Op. Profit Margin", calculation=lambda p, pv: safe_div(operating_income(p), p.get("revenue")), format_type="percentage"),
    Row("Depreciation & Amortization", key="depreciationAndAmortization"),
    Row("EBITDA", calculation=lambda p, pv: ebitda(p), is_bold=True, tooltip="EBIT + D&A (computed, not FMP's raw field)", estimate_key="ebitda"),
    Row("EBITDA Margin", calculation=lambda p, pv: safe_div(ebitda(p), p.get("revenue")), format_type="percentage"),
    Row("Interest Expense", key="interestExpense", is_subheader=True),
    Row("Interest Income", key="interestIncome"),
    Row("Net Interest Expense", calculation=lambda p, pv: net_interest_expense(p), is_bold=True),
    Row("Total Other Income/Expenses, Net", key="totalOtherIncomeExpensesNet"),
    Row("Non-Operating Income (Excl. Interest)", key="nonOperatingIncomeExcludingInterest"),
    Row("EBT", key="incomeBeforeTax"),
    Row("EBIT", calculation=lambda p, pv: ebit(p), is_bold=True, tooltip="EBT + Net Interest Expense (computed, not FMP's raw field)", estimate_key="ebit"),
    Row("Effective Tax Rate", calculation=lambda p, pv: safe_div(p.get("incomeTaxExpense"), p.get("incomeBeforeTax")), format_type="percentage"),
    Row("Income Tax Expense", key="incomeTaxExpense"),
    Row("Net Income From Continuing Operations", key="netIncomeFromContinuingOperations"),
    Row("Net Income From Discontinued Operations", key="netIncomeFromDiscontinuedOperations"),
    Row("Interest Coverage Ratio", calculation=lambda p, pv: safe_div(ebit(p), p.get("interestExpense")), format_type="raw", tooltip="EBIT / Interest Expense"),
    Row("Net Income", key="netIncome", is_bold=True, is_subheader=True, estimate_key="netIncome"),
    Row("Net Income Growth", calculation=lambda p, pv: growth(p, pv, "netIncome"), format_type="percentage"),
    Row("Net Profit Margin", calculation=lambda p, pv: safe_div(p.get("netIncome"), p.get("revenue")), format_type="percentage"),
    Row("Bottom Line Net Income", key="bottomLineNetIncome"),
    Row("EPS", key="eps", format_type="raw", is_subheader=True),
    Row("EPS Diluted", key="epsDiluted", is_bold=True, format_type="raw", estimate_key="eps"),
    Row("Shares Outstanding", key="weightedAverageShsOut", is_subheader=True),
    Row("Shares Outstanding Diluted", key="weightedAverageShsOutDil", is_bold=True),
]

BANK_INCOME_ROWS: list[Row] = [
    Row("Total Revenue", calculation=lambda p, pv: total_bank_revenue(p), is_bold=True, tooltip="Net Interest Income + Non-Interest Income (Yahoo/GuruFocus convention; differs from FMP's raw revenue field)"),
    Row("Net Interest Income", calculation=lambda p, pv: net_interest_income(p), is_bold=True, indent=1, tooltip="Interest Income − Interest Expense"),
    Row("Interest Income", key="interestIncome", indent=2),
    Row("Interest Expense", key="interestExpense", indent=2),
    Row("Non-Interest Income", calculation=lambda p, pv: non_interest_income(p), is_bold=True, indent=1),
    Row("Total Revenue Growth", calculation=lambda p, pv: growth({"v": total_bank_revenue(p)}, {"v": total_bank_revenue(pv)} if pv else None, "v"), format_type="percentage"),
    Row("Net Interest Income Growth", calculation=lambda p, pv: growth({"v": net_interest_income(p)}, {"v": net_interest_income(pv)} if pv else None, "v"), format_type="percentage"),
    Row("Provision for Credit Losses", calculation=lambda p, pv: provision_for_credit_losses(p), tooltip="Estimated as Cost of Revenue − Interest Expense — FMP has no dedicated field for banks"),
    Row("Net Interest Income After Provision", calculation=lambda p, pv: _sub(net_interest_income(p), provision_for_credit_losses(p)), is_bold=True),
    Row("Non-Interest Expense", key="operatingExpenses", is_bold=True),
    Row("SG&A", key="sellingGeneralAndAdministrativeExpenses", indent=1),
    Row("Other Non-Interest Expense", key="otherExpenses", indent=1),
    Row("Pre-Provision Net Revenue (PPNR)", calculation=lambda p, pv: _sub(_sum(net_interest_income(p), non_interest_income(p)) or 0, p.get("operatingExpenses") or 0), is_bold=True, tooltip="Net Interest Income + Non-Interest Income − Non-Interest Expense"),
    Row("Efficiency Ratio", calculation=lambda p, pv: safe_div(p.get("operatingExpenses"), _sum(net_interest_income(p), non_interest_income(p))), is_bold=True, format_type="percentage", tooltip="Non-Interest Expense / (Net Interest Income + Non-Interest Income) — lower is more efficient"),
    Row("Pre-Tax Income (EBT)", key="incomeBeforeTax"),
    Row("Income Tax Expense", key="incomeTaxExpense"),
    Row("Effective Tax Rate", calculation=lambda p, pv: safe_div(p.get("incomeTaxExpense"), p.get("incomeBeforeTax")), format_type="percentage"),
    Row("Minority Interests", calculation=lambda p, pv: minority_interest_income(p), tooltip="Net Income − Net Income from Continuing Operations (FMP has no dedicated field for banks)"),
    Row("Net Income", key="netIncome", is_bold=True, is_subheader=True),
    Row("Net Income Growth", calculation=lambda p, pv: growth(p, pv, "netIncome"), format_type="percentage"),
    Row("Net Profit Margin", calculation=lambda p, pv: safe_div(p.get("netIncome"), total_bank_revenue(p)), format_type="percentage", tooltip="Net Income / Total Revenue (bank convention, not FMP's raw revenue field)"),
    Row("EPS", key="eps", format_type="raw", is_subheader=True),
    Row("EPS Diluted", key="epsDiluted", is_bold=True, format_type="raw"),
    Row("Shares Outstanding", key="weightedAverageShsOut", is_subheader=True),
    Row("Shares Outstanding Diluted", key="weightedAverageShsOutDil", is_bold=True),
]

BALANCE_ROWS: list[Row] = [
    Row("Total Assets", key="totalAssets", is_bold=True),
    Row("Current Assets", key="totalCurrentAssets", is_bold=True, indent=1),
    Row("Cash & Short Term Investments", key="cashAndShortTermInvestments", indent=2),
    Row("Cash & Equivalents", key="cashAndCashEquivalents", indent=3),
    Row("Short Term Investments", key="shortTermInvestments", indent=3),
    Row("Receivables", key="netReceivables", indent=2),
    Row("Accounts Receivable", key="accountsReceivables", indent=3),
    Row("Other Receivables", key="otherReceivables", indent=3),
    Row("Inventory", key="inventory", indent=2),
    Row("Prepaid Expenses", key="prepaids", indent=2),
    Row("Other Current Assets", key="otherCurrentAssets", indent=2),
    Row("Long-Term Assets", key="totalNonCurrentAssets", is_bold=True, indent=1),
    Row("Gross Property, Plant & Equipment", key="propertyPlantEquipmentNet", indent=2),
    Row("Long-Term Investments", key="longTermInvestments", indent=2),
    Row("Goodwill & Intangible Assets", key="goodwillAndIntangibleAssets", indent=2),
    Row("Goodwill", key="goodwill", indent=3),
    Row("Other Intangibles", key="intangibleAssets", indent=3),
    Row("Tax Assets", key="taxAssets", indent=2),
    Row("Other Long-Term Assets", key="otherNonCurrentAssets", indent=2),
    Row("Other Assets", key="otherAssets", indent=1),
    Row("Total Investments (ST + LT)", key="totalInvestments"),
    Row("Goodwill / Total Assets", calculation=lambda p, pv: safe_div(p.get("goodwill"), p.get("totalAssets")), format_type="percentage"),
    Row("Total Liabilities", key="totalLiabilities", is_bold=True, is_subheader=True),
    Row("Current Liabilities", key="totalCurrentLiabilities", is_bold=True, indent=1),
    Row("Payables", key="totalPayables", indent=2),
    Row("Account Payables", key="accountPayables", indent=3),
    Row("Tax Payables", key="taxPayables", indent=3),
    Row("Other Payables", key="otherPayables", indent=3),
    Row("Short-Term Financial Debt", calculation=lambda p, pv: _sum(p.get("shortTermDebt"), p.get("capitalLeaseObligationsCurrent")), indent=2),
    Row("Short Term Debt", key="shortTermDebt", indent=3),
    Row("Current Lease Liabilities", key="capitalLeaseObligationsCurrent", indent=3),
    Row("Deferred Revenue, Current", key="deferredRevenue", indent=2),
    Row("Accrued Expenses", key="accruedExpenses", indent=2),
    Row("Other Current Liabilities", key="otherCurrentLiabilities", indent=2),
    Row("Long-Term Liabilities", key="totalNonCurrentLiabilities", is_bold=True, indent=1),
    Row("Long-Term Financial Debt", calculation=lambda p, pv: _sum(p.get("longTermDebt"), p.get("capitalLeaseObligationsNonCurrent")), indent=2),
    Row("Long Term Debt", key="longTermDebt", indent=3),
    Row("Non-Current Lease Liabilities", key="capitalLeaseObligationsNonCurrent", indent=3),
    Row("Deferred Revenue, Non-Current", key="deferredRevenueNonCurrent", indent=2),
    Row("Deferred Tax Liability, Non-Current", key="deferredTaxLiabilitiesNonCurrent", indent=2),
    Row("Other Non-Current Liabilities", key="otherNonCurrentLiabilities", indent=2),
    Row("Other Liabilities", key="otherLiabilities", is_bold=True, indent=1),
    Row("Total Financial Debt", calculation=lambda p, pv: total_financial_debt(p), is_bold=True, is_subheader=True),
    Row("Net Debt", calculation=lambda p, pv: net_debt_computed(p), is_bold=True, tooltip="Total Financial Debt − Cash & Short-Term Investments (differs from FMP's raw netDebt field, which only subtracts Cash & Equivalents)"),
    Row("Total Equity", key="totalEquity", is_bold=True, is_subheader=True),
    Row("Stockholders' Equity", calculation=lambda p, pv: _sum(p.get("preferredStock"), p.get("totalStockholdersEquity")), is_bold=True, indent=1),
    Row("Preferred Equity", key="preferredStock", indent=2),
    Row("Common Equity", key="totalStockholdersEquity", indent=2),
    Row("Common Stock", key="commonStock", indent=3),
    Row("Retained Earnings", key="retainedEarnings", indent=3),
    Row("Accumulated Comprehensive Income (Loss)", key="accumulatedOtherComprehensiveIncomeLoss", indent=3),
    Row("Treasury Stock", key="treasuryStock", indent=3),
    Row("Additional Paid-In Capital", key="additionalPaidInCapital", indent=3),
    Row("Non-Controlling Interest", key="minorityInterest", is_bold=True, indent=1),
    Row("Total Liabilities + Equity", key="totalLiabilitiesAndTotalEquity", is_bold=True),
    Row("Debt/Capital", calculation=lambda p, pv: safe_div(total_financial_debt(p), _sum(total_financial_debt(p), p.get("totalEquity"))), format_type="percentage", is_subheader=True),
    Row("Debt/Equity", calculation=lambda p, pv: safe_div(total_financial_debt(p), p.get("totalEquity")), format_type="percentage"),
    Row("Current Ratio", calculation=lambda p, pv: safe_div(p.get("totalCurrentAssets"), p.get("totalCurrentLiabilities")), format_type="raw"),
    Row("Quick Ratio", calculation=lambda p, pv: safe_div(_sub(p.get("totalCurrentAssets"), p.get("inventory")), p.get("totalCurrentLiabilities")), format_type="raw"),
    Row("Working Capital", calculation=lambda p, pv: _sub(p.get("totalCurrentAssets"), p.get("totalCurrentLiabilities"))),
]

BANK_BALANCE_ROWS: list[Row] = [
    Row("Total Assets", key="totalAssets", is_bold=True),
    Row("Loans, Securities & Cash", calculation=lambda p, pv: _sub(_sub(p.get("totalAssets"), p.get("propertyPlantEquipmentNet") or 0), p.get("goodwillAndIntangibleAssets") or 0), is_bold=True, indent=1, tooltip="Total Assets − Net PPE − Goodwill & Intangible Assets — FMP doesn't reliably separate loans/securities/cash for banks, aggregated here as the dominant residual"),
    Row("Net PPE", key="propertyPlantEquipmentNet", indent=2),
    Row("Goodwill & Intangible Assets", key="goodwillAndIntangibleAssets", indent=2),
    Row("Total Liabilities", key="totalLiabilities", is_bold=True, is_subheader=True),
    Row("Deposits & Other Liabilities", calculation=lambda p, pv: _sub(p.get("totalLiabilities"), p.get("longTermDebt") or 0), is_bold=True, indent=1, tooltip="Total Liabilities − Long-Term Debt — FMP has no dedicated Deposits field for banks, aggregated here as the dominant residual"),
    Row("Long-Term Debt", key="longTermDebt", indent=2),
    Row("Total Equity", key="totalEquity", is_bold=True, is_subheader=True),
    Row("Stockholders' Equity", key="totalStockholdersEquity", is_bold=True, indent=1),
    Row("Common Stock", key="commonStock", indent=2),
    Row("Preferred Stock", key="preferredStock", indent=2),
    Row("Additional Paid-in Capital", key="additionalPaidInCapital", indent=2),
    Row("Retained Earnings", key="retainedEarnings", indent=2),
    Row("Accumulated Other Comprehensive Income (Loss)", key="accumulatedOtherComprehensiveIncomeLoss", indent=2),
    Row("Treasury Stock", key="treasuryStock", indent=2),
    Row("Minority Interest", key="minorityInterest", indent=1),
    Row("Equity / Assets", calculation=lambda p, pv: safe_div(p.get("totalEquity"), p.get("totalAssets")), format_type="percentage", is_subheader=True, tooltip="Capitalization/leverage — higher means less reliance on debt/deposit funding"),
    Row(
        "Tangible Common Equity Ratio (TCE)",
        calculation=lambda p, pv: safe_div(
            _sub(_sub(p.get("totalStockholdersEquity"), p.get("preferredStock") or 0), p.get("goodwillAndIntangibleAssets") or 0),
            _sub(p.get("totalAssets"), p.get("goodwillAndIntangibleAssets") or 0),
        ),
        is_bold=True,
        format_type="percentage",
        tooltip="(Stockholders' Equity − Preferred Stock − Goodwill & Intangibles) / (Total Assets − Goodwill & Intangibles) — key capital-adequacy metric",
    ),
    Row("Goodwill", key="goodwill", is_subheader=True),
    Row("Goodwill / Total Assets", calculation=lambda p, pv: safe_div(p.get("goodwill"), p.get("totalAssets")), format_type="percentage"),
]

CASH_ROWS: list[Row] = [
    Row("Operating Cash Flow", key="operatingCashFlow", is_bold=True),
    Row("Cash Flow from Continuing Operating Activities", key="netCashProvidedByOperatingActivities", indent=1),
    Row("Net Income from Continuing Operating Activities", key="netIncome", indent=2),
    Row("Depreciation & Amortization", key="depreciationAndAmortization", is_bold=True, indent=2),
    Row("Deferred Income Tax", key="deferredIncomeTax", indent=2),
    Row("Stock-based Compensation", key="stockBasedCompensation", is_bold=True, indent=2),
    Row("Other non-cash items", key="otherNonCashItems", indent=2),
    Row("Change in working capital", key="changeInWorkingCapital", indent=2),
    Row("Accounts Receivable", key="accountsReceivables", indent=3),
    Row("Accounts Payable", key="accountsPayables", indent=3),
    Row("Other Working Capital", key="otherWorkingCapital", indent=3),
    Row("Investing Cash Flow", key="netCashProvidedByInvestingActivities", is_bold=True, is_subheader=True),
    Row("Net PPE Purchase And Sale", key="investmentsInPropertyPlantAndEquipment", indent=1),
    Row("Net Business Purchase And Sale", key="acquisitionsNet", indent=1),
    Row("Net Investment Purchase", calculation=lambda p, pv: _sum(p.get("purchasesOfInvestments"), p.get("salesMaturitiesOfInvestments")), indent=1),
    Row("Purchase of Investment", key="purchasesOfInvestments", indent=2),
    Row("Sale of Investment", key="salesMaturitiesOfInvestments", indent=2),
    Row("Net Other Investing Changes", key="otherInvestingActivities", indent=1),
    Row("Financing Cash Flow", key="netCashProvidedByFinancingActivities", is_bold=True, is_subheader=True),
    Row("Net Stock Issuance", key="netStockIssuance", indent=1),
    Row("Net Common Stock Issuance", key="netCommonStockIssuance", indent=2),
    Row("Common Stock Issuance", key="commonStockIssuance", indent=3),
    Row("Stock Buybacks", calculation=lambda p, pv: _neg(p.get("commonStockRepurchased")), indent=3),
    Row("Net Debt Issuance", key="netDebtIssuance", indent=1),
    Row("Long-Term Debt Issuance", key="longTermNetDebtIssuance", indent=2),
    Row("Short-Term Debt Issuance", key="shortTermNetDebtIssuance", indent=2),
    Row("Dividends Paid", calculation=lambda p, pv: p.get("netDividendsPaid"), indent=1),
    Row("Other Financing Activities", key="otherFinancingActivities", indent=1),
    Row("Net Change in Cash", key="netChangeInCash", is_bold=True, is_subheader=True),
    Row("Effect of Forex Changes on Cash", key="effectOfForexChangesOnCash", indent=1),
    Row("Cash at Beginning of Period", key="cashAtBeginningOfPeriod"),
    Row("Cash at End of Period", key="cashAtEndOfPeriod", is_bold=True),
    Row("Capital Expenditure", calculation=lambda p, pv: _neg(p.get("capitalExpenditure")), is_bold=True, is_subheader=True),
    Row("Growth CapEx (CapEx - D&A)", calculation=lambda p, pv: _sub(_neg(p.get("capitalExpenditure")), p.get("depreciationAndAmortization"))),
    Row("Free Cash Flow", key="freeCashFlow", is_bold=True, is_subheader=True, tooltip="Operating Cash Flow − Capital Expenditure"),
    Row("FCF Growth", calculation=lambda p, pv: growth(p, pv, "freeCashFlow"), format_type="percentage"),
    Row("FCF/Share", calculation=lambda p, pv: safe_div(p.get("freeCashFlow"), p.get("weightedAverageShsOutDil")), format_type="raw", tooltip="Free Cash Flow / Shares Outstanding Diluted"),
    Row("Dividends Paid", calculation=lambda p, pv: _neg(p.get("netDividendsPaid")), is_bold=True, is_subheader=True),
    Row("Common Dividends Paid", calculation=lambda p, pv: _neg(p.get("commonDividendsPaid")), indent=1),
    Row("Preferred Dividends Paid", calculation=lambda p, pv: _neg(p.get("preferredDividendsPaid")), indent=1),
    Row("Dividends/Share", calculation=lambda p, pv: safe_div(_neg(p.get("netDividendsPaid")), p.get("weightedAverageShsOutDil")), format_type="raw"),
    Row("Interest Paid", key="interestPaid", is_subheader=True),
    Row("Income Taxes Paid", key="incomeTaxesPaid"),
    Row("Buybacks per Share Outstanding", calculation=lambda p, pv: safe_div(_neg(p.get("commonStockRepurchased")), p.get("weightedAverageShsOutDil")), format_type="raw", is_subheader=True, tooltip="$ spent on buybacks per existing share — not the average price paid per repurchased share"),
    Row("Total Shareholder Return / Share", calculation=lambda p, pv: safe_div(_sum(_neg(p.get("netDividendsPaid")), _neg(p.get("netCommonStockIssuance"))), p.get("weightedAverageShsOutDil")), is_bold=True, format_type="raw", tooltip="Cash returned to shareholders (dividends + net share buybacks) per diluted share"),
]

# Bank cash flow config mirrors the default closely (same underlying
# statement, same fields) — only the tooltips differ (FMP's generic
# "Other" buckets absorb bank-specific line items FMP doesn't break out:
# credit-loss provisions, loan flows, deposit changes). Reuse CASH_ROWS
# with those 3 tooltips swapped in, rather than duplicating ~40 rows.
def _with_tooltip(rows: list[Row], label: str, tooltip: str) -> list[Row]:
    return [
        Row(**{**r.__dict__, "tooltip": tooltip}) if r.label == label else r
        for r in rows
    ]


BANK_CASH_ROWS: list[Row] = CASH_ROWS
for _label, _tooltip in [
    ("Other non-cash items", "For banks, FMP's generic field usually also absorbs the Provision for Credit Losses — a significant non-cash cost shown as its own line by Yahoo/GuruFocus, which FMP doesn't isolate in the cash flow statement."),
    ("Net Other Investing Changes", "FMP's generic \"Other Investing Activities\" field — for banks, dominated by net loan origination/collection flows, which FMP doesn't separate into a dedicated field."),
    ("Other Financing Activities", "FMP's generic field — for banks, dominated by the net change in customer deposits (a bank's primary funding source), which FMP doesn't separate into a dedicated field."),
]:
    BANK_CASH_ROWS = _with_tooltip(BANK_CASH_ROWS, _label, _tooltip)


# ---------------------------------------------------------------------------
# View recommendation
# ---------------------------------------------------------------------------


async def recommend_view(symbol: str) -> str:
    """"default" or "banks" — industry label first (FMP's own "Banks -
    Regional"/"Banks - Diversified"), falling back to a data signal
    (interestIncome/revenue > 20% of latest annual revenue) since some
    bank-like companies (e.g. AXP, MS) aren't labeled as banks.
    """
    profile, income = await asyncio.gather(
        get_company_profile(symbol),
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, limit=1),
    )
    if profile.get("industry") in _BANK_INDUSTRIES:
        return "banks"
    latest = income[0] if isinstance(income, list) and income else {}
    revenue = latest.get("revenue") or 0
    interest_income = latest.get("interestIncome") or 0
    if revenue and (interest_income / revenue) > _BANK_INTEREST_INCOME_THRESHOLD:
        return "banks"
    return "default"


# ---------------------------------------------------------------------------
# Fetch + assemble
# ---------------------------------------------------------------------------

_ROW_CONFIGS: dict[str, dict[str, list[Row]]] = {
    "income": {"default": INCOME_ROWS, "banks": BANK_INCOME_ROWS},
    "balance": {"default": BALANCE_ROWS, "banks": BANK_BALANCE_ROWS},
    "cash": {"default": CASH_ROWS, "banks": BANK_CASH_ROWS},
}
_ENDPOINTS = {
    "income": "income-statement",
    "balance": "balance-sheet-statement",
    "cash": "cash-flow-statement",
}

# Default `limit` when the caller doesn't specify one — 15 years for
# annual/FY; 20 for "quarter" (5 years of quarterly history). Single-quarter
# seasonal mode (Q1-Q4) falls back to the 15 default too, no separate
# guidance for that mode.
_DEFAULT_LIMITS: dict[str, int] = {"quarter": 20}
_FALLBACK_LIMIT = 15


_ESTIMATE_FIELD_MAP = {
    "revenue": "revenueAvg",
    "ebitda": "ebitdaAvg",
    "ebit": "ebitAvg",
    "netIncome": "netIncomeAvg",
    "eps": "epsAvg",
}


async def _get_income_estimate_periods(symbol: str, latest_historical_date: str) -> list[dict]:
    """Forward analyst-estimate years strictly after the latest reported one.

    FMP's `analyst-estimates` (period="annual") returns both past and future
    fiscal years for whatever range analysts cover — anywhere from 0 to ~5+
    years out, never a fixed count. We never decide the count ourselves; we
    just keep rows dated after the most recently reported statement.
    Filtering must be a date comparison, not "not in the fetched historical
    set" — a caller with a small `limit` (e.g. 3 years) only fetches 3
    historical dates, but this endpoint still returns estimate rows for
    older years too, which a mere set-membership check would wrongly treat
    as "future". `fiscalYear` is null on this endpoint, so the year label is
    derived from `date`. Quarterly is never called here — this endpoint
    402s for period="quarter" on the current plan.
    """
    # limit=10 is this endpoint's actual ceiling on the current plan
    # (limit=12+ 402s) — not related to _DEFAULT_LIMITS/_FALLBACK_LIMIT
    # above (those are ours; this is FMP's own plan-tier cap on this
    # specific endpoint).
    raw = await asyncio.to_thread(
        fmp_get, "analyst-estimates", symbol=symbol, period="annual", limit=10
    )
    future = [r for r in raw if r.get("date") and r["date"] > latest_historical_date]
    future.sort(key=lambda r: r["date"])
    periods = []
    for r in future:
        p = {"date": r["date"]}
        for norm_key, fmp_key in _ESTIMATE_FIELD_MAP.items():
            p[norm_key] = r.get(fmp_key)
        periods.append(p)
    return periods


async def get_statement_table(
    symbol: str,
    statement: str,
    view: str = "default",
    period: str = "annual",
    limit: int | None = None,
) -> dict:
    """`statement`: "income" | "balance" | "cash". `view`: "default" | "banks".
    `period`: "annual" | "quarter" | "FY" | "Q1" | "Q2" | "Q3" | "Q4" — FMP
    supports all of these directly on all 3 statement endpoints:
    "annual"/"FY" return one row per fiscal year, "quarter" returns the
    last N quarters sequentially, and "Q1".."Q4" return only that single
    quarter across N years (e.g. "Q1" → every Q1 report, for seasonal
    year-over-year comparison). `limit` is the number of periods returned
    either way. Defaults to `_DEFAULT_LIMITS`/`_FALLBACK_LIMIT` when
    omitted — 20 (5 years) for "quarter", 15 otherwise.

    For statement="income", view="default", period in ("annual", "FY"): forward
    analyst-estimate years are appended after the historical columns (however
    many FMP actually returns beyond reported history — never a fixed count),
    populating only the 5 rows with an `estimate_key` (Revenue, EBITDA, EBIT,
    Net Income, EPS Diluted); every other row is blank in estimate columns.
    Not applied to quarterly/Q1-Q4 (the estimates endpoint doesn't support
    period="quarter" on this plan) or to the banks view (no estimate mapping
    defined for BANK_INCOME_ROWS).
    """
    if limit is None:
        limit = _DEFAULT_LIMITS.get(period, _FALLBACK_LIMIT)

    raw = await asyncio.to_thread(
        fmp_get, _ENDPOINTS[statement], symbol=symbol, period=period, limit=limit
    )
    periods = sorted(raw, key=lambda r: r["date"])[-limit:]

    if statement == "cash":
        # weightedAverageShsOutDil (FCF/Share, Dividends/Share, ...) lives on
        # the income statement, not cash-flow — merge it in by date.
        income_raw = await asyncio.to_thread(
            fmp_get, "income-statement", symbol=symbol, period=period, limit=limit
        )
        shares_by_date = {r["date"]: r.get("weightedAverageShsOutDil") for r in income_raw}
        periods = [{**p, "weightedAverageShsOutDil": shares_by_date.get(p["date"])} for p in periods]

    # Two-line header per column: "FY {year}" / actual period-end date — same
    # for historical and (further below) estimate columns, matching the
    # user's reference project's search.html convention.
    if period not in ("annual", "FY"):
        columns = [
            {"label": f"{p.get('period', '')} {p.get('fiscalYear') or p['date'][:4]}", "date": p["date"], "is_estimate": False}
            for p in periods
        ]
    else:
        columns = [
            {"label": f"FY {p.get('fiscalYear') or p['date'][:4]}", "date": p["date"], "is_estimate": False}
            for p in periods
        ]

    estimate_periods: list[dict] = []
    if statement == "income" and view == "default" and period in ("annual", "FY") and periods:
        estimate_periods = await _get_income_estimate_periods(symbol, periods[-1]["date"])
        columns += [
            {"label": f"FY {p['date'][:4]}", "date": p["date"], "is_estimate": True}
            for p in estimate_periods
        ]

    rows_config = _ROW_CONFIGS[statement][view]
    all_periods = periods + estimate_periods
    n_historical = len(periods)

    rows_out = [
        {
            "label": row.label,
            "is_bold": row.is_bold,
            "is_subheader": row.is_subheader,
            "indent": row.indent,
            "format_type": row.format_type,
            "tooltip": row.tooltip,
            "values": [
                row.value(
                    p,
                    periods[i - 1] if 0 < i < n_historical else None,
                    is_estimate=i >= n_historical,
                )
                for i, p in enumerate(all_periods)
            ],
        }
        for row in rows_config
    ]

    return {"fiscal_years": columns, "rows": rows_out}
