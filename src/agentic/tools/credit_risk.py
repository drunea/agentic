"""Balance-sheet & solvency risk — Altman Z-Score, Piotroski F-Score, Net
Debt/EBITDA, Interest Coverage. 100% deterministic Python, no LLM — same
zero-ambiguity category as Market Risk's VaR/CVaR (tools/risk_modeling.py),
just a different risk dimension: insolvency, not price volatility.

Reuses financial_statements.py's recomputed EBIT/EBITDA/Net Debt (not FMP's
own equivalent fields) for consistency with every other page already built
on those helpers, rather than re-deriving them differently here.
"""

import asyncio

from agentic.data.fmp_client import fmp_get
from agentic.tools.financial_statements import ebit, ebitda, net_debt_computed, safe_div
from agentic.tools.company_profile import get_company_profile

_Z_SAFE_THRESHOLD = 2.99
_Z_DISTRESS_THRESHOLD = 1.81


def _altman_z_score(income0: dict, balance0: dict, market_cap: float | None) -> dict:
    total_assets = balance0.get("totalAssets")
    working_capital = (
        balance0.get("totalCurrentAssets") - balance0.get("totalCurrentLiabilities")
        if balance0.get("totalCurrentAssets") is not None and balance0.get("totalCurrentLiabilities") is not None
        else None
    )
    retained_earnings = balance0.get("retainedEarnings")
    ebit0 = ebit(income0)
    total_liabilities = balance0.get("totalLiabilities")
    revenue = income0.get("revenue")

    x1 = safe_div(working_capital, total_assets)
    x2 = safe_div(retained_earnings, total_assets)
    x3 = safe_div(ebit0, total_assets)
    x4 = safe_div(market_cap, total_liabilities)
    x5 = safe_div(revenue, total_assets)

    components = {
        "working_capital_to_assets": x1,
        "retained_earnings_to_assets": x2,
        "ebit_to_assets": x3,
        "market_cap_to_liabilities": x4,
        "sales_to_assets": x5,
    }
    if any(v is None for v in (x1, x2, x3, x4, x5)):
        return {"z_score": None, "zone": None, "components": components}

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 0.999 * x5
    if z > _Z_SAFE_THRESHOLD:
        zone = "safe"
    elif z < _Z_DISTRESS_THRESHOLD:
        zone = "distress"
    else:
        zone = "grey"
    return {"z_score": round(z, 2), "zone": zone, "components": components}


def _piotroski_f_score(
    income0: dict, income1: dict, balance0: dict, balance1: dict, cash0: dict
) -> dict:
    """9 binary criteria, current period (0) vs. prior period (1). Each
    returns 1 point when the underlying number is missing-but-comparable
    (e.g. can't tell if leverage improved) is impossible to determine — 0
    points in that case, not a guess.
    """
    criteria: dict[str, bool | None] = {}

    net_income0 = income0.get("netIncome")
    total_assets0 = balance0.get("totalAssets")
    total_assets1 = balance1.get("totalAssets")
    roa0 = safe_div(net_income0, total_assets0)
    roa1 = safe_div(income1.get("netIncome"), total_assets1)
    cfo0 = cash0.get("operatingCashFlow")

    criteria["positive_net_income"] = None if net_income0 is None else net_income0 > 0
    criteria["positive_operating_cash_flow"] = None if cfo0 is None else cfo0 > 0
    criteria["roa_improving"] = None if roa0 is None or roa1 is None else roa0 > roa1
    criteria["cfo_exceeds_net_income"] = None if cfo0 is None or net_income0 is None else cfo0 > net_income0

    leverage0 = safe_div(balance0.get("longTermDebt"), total_assets0)
    leverage1 = safe_div(balance1.get("longTermDebt"), total_assets1)
    criteria["leverage_decreasing"] = None if leverage0 is None or leverage1 is None else leverage0 < leverage1

    current_ratio0 = safe_div(balance0.get("totalCurrentAssets"), balance0.get("totalCurrentLiabilities"))
    current_ratio1 = safe_div(balance1.get("totalCurrentAssets"), balance1.get("totalCurrentLiabilities"))
    criteria["current_ratio_improving"] = (
        None if current_ratio0 is None or current_ratio1 is None else current_ratio0 > current_ratio1
    )

    shares0 = income0.get("weightedAverageShsOut")
    shares1 = income1.get("weightedAverageShsOut")
    criteria["no_new_shares_issued"] = None if shares0 is None or shares1 is None else shares0 <= shares1

    margin0 = safe_div(income0.get("grossProfit"), income0.get("revenue"))
    margin1 = safe_div(income1.get("grossProfit"), income1.get("revenue"))
    criteria["gross_margin_improving"] = None if margin0 is None or margin1 is None else margin0 > margin1

    turnover0 = safe_div(income0.get("revenue"), total_assets0)
    turnover1 = safe_div(income1.get("revenue"), total_assets1)
    criteria["asset_turnover_improving"] = None if turnover0 is None or turnover1 is None else turnover0 > turnover1

    determined = [v for v in criteria.values() if v is not None]
    score = sum(1 for v in determined if v)
    return {"f_score": score, "criteria_determined": len(determined), "criteria": criteria}


async def get_credit_risk(symbol: str) -> dict:
    profile, income_periods, balance_periods, cash_periods = await asyncio.gather(
        get_company_profile(symbol),
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, period="annual", limit=2),
        asyncio.to_thread(fmp_get, "balance-sheet-statement", symbol=symbol, period="annual", limit=2),
        asyncio.to_thread(fmp_get, "cash-flow-statement", symbol=symbol, period="annual", limit=1),
    )
    income_periods = sorted(income_periods, key=lambda r: r["date"], reverse=True) if income_periods else []
    balance_periods = sorted(balance_periods, key=lambda r: r["date"], reverse=True) if balance_periods else []
    cash_periods = sorted(cash_periods, key=lambda r: r["date"], reverse=True) if cash_periods else []

    if not income_periods or not balance_periods:
        return {
            "altman_z_score": None,
            "altman_zone": None,
            "altman_components": {},
            "piotroski_f_score": None,
            "piotroski_criteria_determined": 0,
            "piotroski_criteria": {},
            "net_debt_to_ebitda": None,
            "interest_coverage_ratio": None,
            "latest_period_date": None,
        }

    income0 = income_periods[0]
    balance0 = balance_periods[0]
    cash0 = cash_periods[0] if cash_periods else {}
    market_cap = profile.get("market_cap")

    altman = _altman_z_score(income0, balance0, market_cap)

    if len(income_periods) >= 2 and len(balance_periods) >= 2:
        piotroski = _piotroski_f_score(income0, income_periods[1], balance0, balance_periods[1], cash0)
    else:
        piotroski = {"f_score": None, "criteria_determined": 0, "criteria": {}}

    ebitda0 = ebitda(income0)
    net_debt0 = net_debt_computed(balance0)
    net_debt_to_ebitda = safe_div(net_debt0, ebitda0)

    ebit0 = ebit(income0)
    interest_expense = income0.get("interestExpense")
    interest_coverage_ratio = safe_div(ebit0, interest_expense)

    return {
        "altman_z_score": altman["z_score"],
        "altman_zone": altman["zone"],
        "altman_components": altman["components"],
        "piotroski_f_score": piotroski["f_score"],
        "piotroski_criteria_determined": piotroski["criteria_determined"],
        "piotroski_criteria": piotroski["criteria"],
        "net_debt_to_ebitda": round(net_debt_to_ebitda, 2) if net_debt_to_ebitda is not None else None,
        "interest_coverage_ratio": round(interest_coverage_ratio, 2) if interest_coverage_ratio is not None else None,
        "latest_period_date": income0.get("date"),
    }
