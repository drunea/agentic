"""Plain Python, no LLM.

Two independent risk dimensions, both zero-ambiguity: Market Risk (Monte
Carlo VaR/CVaR — a statistical simulation with one, up-to-random-seed,
correct answer) and Balance Sheet & Solvency (Altman Z-Score/Piotroski
F-Score — fixed published formulas, industry-convention thresholds).
Nothing for an LLM to add to either.
"""

import asyncio

from agentic.data.base import DataProvider
from agentic.schemas.risk import RiskReport
from agentic.tools.credit_risk import get_credit_risk
from agentic.tools.macro_data import get_rate_environment
from agentic.tools.risk_modeling import run_monte_carlo_var


def _classify_risk_level(var_pct: float | None) -> str:
    if var_pct is None:
        return "unknown"
    magnitude = abs(var_pct)
    if magnitude < 5:
        return "low"
    if magnitude <= 15:
        return "moderate"
    return "high"


async def analyze_risk(provider: DataProvider, symbol: str) -> RiskReport:
    var_result, rate_env, credit = await asyncio.gather(
        run_monte_carlo_var(provider, symbol), get_rate_environment(), get_credit_risk(symbol)
    )

    var_pct = var_result.get("var_pct")
    cvar_pct = var_result.get("cvar_pct")
    rate_latest = rate_env.get("latest_value")
    z_score = credit.get("altman_z_score")
    f_score = credit.get("piotroski_f_score")

    caveats = []
    if var_pct is None:
        caveats.append("Insufficient price history for Monte Carlo simulation")
    if rate_latest is None:
        caveats.append("Rate environment data unavailable")
    if z_score is None:
        caveats.append("Insufficient balance sheet data for Altman Z-Score")
    if f_score is None:
        caveats.append("Fewer than 2 annual periods available for Piotroski F-Score")

    confidence = 1.0
    if var_pct is None:
        confidence -= 0.4
    if rate_latest is None:
        confidence -= 0.1
    if z_score is None:
        confidence -= 0.2
    if f_score is None:
        confidence -= 0.1
    confidence = max(0.0, round(confidence, 2))

    risk_level = _classify_risk_level(var_pct)

    # Rate environment and credit risk (FMP balance sheet/income data) are
    # always fixed sources; VaR/CVaR come through the provider fallback
    # chain (FMP/yfinance), so its actual source can vary run to run.
    sources = {"fred", "fmp"}
    var_source = var_result.get("data_source")
    if var_source:
        sources.add(var_source)
    data_source = ", ".join(sorted(sources))

    if var_pct is not None:
        summary = (
            f"{symbol}: {risk_level} market risk — {int(var_result['confidence_level'] * 100)}% "
            f"VaR ({var_result['horizon_days']}d) is {var_pct}%, CVaR {cvar_pct}%."
        )
    else:
        summary = f"{symbol}: market risk level unknown — insufficient price history for VaR simulation."
    if rate_latest is not None:
        summary += f" 10Y Treasury yield: {rate_latest}%."
    if z_score is not None:
        summary += f" Altman Z-Score {z_score} ({credit.get('altman_zone')} zone)."
    if f_score is not None:
        summary += f" Piotroski F-Score {f_score}/9."

    return RiskReport(
        symbol=symbol,
        confidence=confidence,
        caveats=caveats,
        data_source=data_source,
        var_pct=var_pct,
        cvar_pct=cvar_pct,
        confidence_level=var_result["confidence_level"],
        horizon_days=var_result["horizon_days"],
        rate_environment_series=rate_env["series_id"],
        rate_environment_latest=rate_latest,
        rate_environment_previous=rate_env.get("previous_value"),
        risk_level=risk_level,
        altman_z_score=z_score,
        altman_zone=credit.get("altman_zone"),
        altman_components=credit.get("altman_components", {}),
        piotroski_f_score=f_score,
        piotroski_criteria_determined=credit.get("piotroski_criteria_determined", 0),
        piotroski_criteria=credit.get("piotroski_criteria", {}),
        net_debt_to_ebitda=credit.get("net_debt_to_ebitda"),
        interest_coverage_ratio=credit.get("interest_coverage_ratio"),
        credit_risk_period_date=credit.get("latest_period_date"),
        summary=summary,
    )
