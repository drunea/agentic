"""ROE + DuPont (3/5-factor), ROCE, ROIC vs. WACC, RORE — all computed from
raw annual statement lines (the same period dicts and recomputed `ebit()`/
`total_financial_debt()` used throughout financial_statements.py), not from
FMP's own derived ratio fields (`ratios-ttm`/`key-metrics-ttm`). Everything
uses the latest reported annual period, not TTM.

WACC stays CAPM-based (ported from an existing dcf_model.py methodology) —
not independently re-verified, but no alternative formula was specified.
"""

import asyncio

from agentic.data.fmp_client import fmp_get
from agentic.tools.financial_statements import (
    _BANK_INDUSTRIES,
    _BANK_INTEREST_INCOME_THRESHOLD,
    _neg,
    _sub,
    _sum,
    ebit,
    safe_div,
    total_financial_debt,
)
from agentic.tools.macro_data import get_rate_environment
from agentic.tools.company_profile import get_company_profile

_EQUITY_RISK_PREMIUM = 0.055
_DEBT_CREDIT_SPREAD = 0.015  # over risk-free, used only when interest expense is ~0
_RORE_YEARS = 5
_DEFAULT_TAX_RATE = 0.21  # fallback when EBT is missing/zero


async def get_wacc(symbol: str) -> dict:
    profile, rate_env, income, balance = await asyncio.gather(
        get_company_profile(symbol),
        get_rate_environment(),
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, limit=1),
        asyncio.to_thread(fmp_get, "balance-sheet-statement", symbol=symbol, limit=1),
    )
    income0 = income[0] if isinstance(income, list) and income else {}
    balance0 = balance[0] if isinstance(balance, list) and balance else {}

    beta = profile.get("beta")
    risk_free = rate_env.get("latest_value")
    if beta is None or risk_free is None:
        return {"wacc": None, "cost_of_equity": None, "cost_of_debt_after_tax": None}
    risk_free_frac = risk_free / 100

    cost_of_equity = risk_free_frac + beta * _EQUITY_RISK_PREMIUM

    total_debt = balance0.get("totalDebt") or 0
    interest_expense = income0.get("interestExpense") or 0
    tax_rate = income0.get("incomeTaxExpense", 0) / income0.get("incomeBeforeTax", 1) if income0.get("incomeBeforeTax") else 0.21

    if total_debt > 0 and interest_expense > 0:
        cost_of_debt = interest_expense / total_debt
    else:
        cost_of_debt = risk_free_frac + _DEBT_CREDIT_SPREAD
    cost_of_debt_after_tax = cost_of_debt * (1 - tax_rate)

    market_cap = profile.get("market_cap") or 0
    total_value = market_cap + total_debt
    if total_value <= 0:
        return {"wacc": None, "cost_of_equity": round(cost_of_equity * 100, 2), "cost_of_debt_after_tax": None}

    equity_weight = market_cap / total_value
    debt_weight = total_debt / total_value
    wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt_after_tax

    return {
        "wacc": round(wacc * 100, 2),
        "cost_of_equity": round(cost_of_equity * 100, 2),
        "cost_of_debt_after_tax": round(cost_of_debt_after_tax * 100, 2),
    }


def _tax_rate(income_period: dict) -> float:
    ebt = income_period.get("incomeBeforeTax")
    tax = income_period.get("incomeTaxExpense")
    if not ebt or tax is None:
        return _DEFAULT_TAX_RATE
    return tax / ebt


def _dividends_per_share(cash_period: dict, shares: float | None) -> float | None:
    return safe_div(_neg(cash_period.get("netDividendsPaid")), shares)


def _is_bank_or_reit(profile: dict, latest_income: dict) -> bool:
    """ROIC (NOPAT / Invested Capital, where Invested Capital nets out cash)
    doesn't mean much for banks (interest income/expense IS the core
    business, not a financing cost the "EBIT" split assumes) or REITs
    (asset-heavy, debt-financed real estate — cap-rate-driven returns, not
    an invested-capital-excluding-financing framework). ROCE/DuPont stay
    computed regardless — only ROIC drops for these two sectors.
    """
    industry = profile.get("industry") or ""
    if industry in _BANK_INDUSTRIES or industry.startswith("REIT"):
        return True
    revenue = latest_income.get("revenue") or 0
    interest_income = latest_income.get("interestIncome") or 0
    return bool(revenue) and (interest_income / revenue) > _BANK_INTEREST_INCOME_THRESHOLD


async def get_capital_efficiency(symbol: str) -> dict:
    wacc_data, profile, income_periods, balance_periods, cash_periods = await asyncio.gather(
        get_wacc(symbol),
        get_company_profile(symbol),
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, period="annual", limit=_RORE_YEARS),
        asyncio.to_thread(fmp_get, "balance-sheet-statement", symbol=symbol, period="annual", limit=_RORE_YEARS),
        asyncio.to_thread(fmp_get, "cash-flow-statement", symbol=symbol, period="annual", limit=_RORE_YEARS),
    )
    income_periods = sorted(income_periods, key=lambda r: r["date"])
    balance_periods = sorted(balance_periods, key=lambda r: r["date"])
    cash_periods = sorted(cash_periods, key=lambda r: r["date"])

    wacc = wacc_data["wacc"]
    empty = {
        "roe_pct": None,
        "roce_pct": None,
        "roic_pct": None,
        "rore_pct": None,
        "wacc_pct": wacc,
        "cost_of_equity_pct": wacc_data["cost_of_equity"],
        "cost_of_debt_after_tax_pct": wacc_data["cost_of_debt_after_tax"],
        "eva": None,
        "invested_capital": None,
        "capital_employed": None,
        "dupont_3factor": {"net_margin_pct": None, "asset_turnover": None, "financial_leverage": None},
        "dupont_5factor": {
            "tax_burden": None,
            "interest_burden": None,
            "operating_margin_pct": None,
            "asset_turnover": None,
            "financial_leverage": None,
        },
    }
    if not income_periods or not balance_periods:
        return empty

    income0 = income_periods[-1]
    balance0 = balance_periods[-1]

    net_income = income0.get("netIncome")
    revenue = income0.get("revenue")
    ebt = income0.get("incomeBeforeTax")
    ebit0 = ebit(income0)
    total_assets = balance0.get("totalAssets")
    total_equity = balance0.get("totalEquity")

    roe = safe_div(net_income, total_equity)
    net_margin = safe_div(net_income, revenue)
    asset_turnover = safe_div(revenue, total_assets)
    financial_leverage = safe_div(total_assets, total_equity)

    tax_burden = safe_div(net_income, ebt)
    interest_burden = safe_div(ebt, ebit0)
    operating_margin = safe_div(ebit0, revenue)

    current_liabilities = balance0.get("totalCurrentLiabilities")
    capital_employed = _sub(total_assets, current_liabilities)
    roce = safe_div(ebit0, capital_employed)

    tax_rate = _tax_rate(income0)
    nopat = ebit0 * (1 - tax_rate) if ebit0 is not None else None
    total_debt = total_financial_debt(balance0)
    cash_and_sti = balance0.get("cashAndShortTermInvestments")
    invested_capital = _sub(_sum(total_debt, total_equity), cash_and_sti)
    roic = None if _is_bank_or_reit(profile, income0) else safe_div(nopat, invested_capital)

    eva = None
    if nopat is not None and invested_capital and wacc is not None:
        eva = round(nopat - invested_capital * (wacc / 100), 2)

    # RORE = (latest Diluted EPS − Diluted EPS 4 years earlier) /
    # (sum of Diluted EPS over the last 5 reported years − sum of
    # Dividends/Share over the same 5 years) — matched by fiscal-year date,
    # not position, in case the two statements return different counts.
    rore = None
    eps_by_date = {p["date"]: p.get("epsDiluted") for p in income_periods}
    shares_by_date = {p["date"]: p.get("weightedAverageShsOutDil") for p in income_periods}
    dps_by_date = {p["date"]: _dividends_per_share(p, shares_by_date.get(p["date"])) for p in cash_periods}
    common_dates = sorted(set(eps_by_date) & set(dps_by_date))[-_RORE_YEARS:]
    if len(common_dates) == _RORE_YEARS:
        eps_series = [eps_by_date[d] for d in common_dates]
        dps_series = [dps_by_date[d] for d in common_dates]
        if all(v is not None for v in eps_series) and all(v is not None for v in dps_series):
            denom = sum(eps_series) - sum(dps_series)
            rore = safe_div(eps_series[-1] - eps_series[0], denom)

    return {
        "roe_pct": round(roe * 100, 2) if roe is not None else None,
        "roce_pct": round(roce * 100, 2) if roce is not None else None,
        "roic_pct": round(roic * 100, 2) if roic is not None else None,
        "rore_pct": round(rore * 100, 2) if rore is not None else None,
        "wacc_pct": wacc,
        "cost_of_equity_pct": wacc_data["cost_of_equity"],
        "cost_of_debt_after_tax_pct": wacc_data["cost_of_debt_after_tax"],
        "eva": eva,
        "invested_capital": invested_capital,
        "capital_employed": capital_employed,
        "dupont_3factor": {
            "net_margin_pct": round(net_margin * 100, 2) if net_margin is not None else None,
            "asset_turnover": round(asset_turnover, 2) if asset_turnover is not None else None,
            "financial_leverage": round(financial_leverage, 2) if financial_leverage is not None else None,
        },
        "dupont_5factor": {
            "tax_burden": round(tax_burden, 3) if tax_burden is not None else None,
            "interest_burden": round(interest_burden, 3) if interest_burden is not None else None,
            "operating_margin_pct": round(operating_margin * 100, 2) if operating_margin is not None else None,
            "asset_turnover": round(asset_turnover, 2) if asset_turnover is not None else None,
            "financial_leverage": round(financial_leverage, 2) if financial_leverage is not None else None,
        },
    }
