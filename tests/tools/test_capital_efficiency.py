import agentic.tools.capital_efficiency as capital_efficiency

# Fixture data models one company's latest annual filing. Reference values
# below were computed independently from the same formulas documented in
# capital_efficiency.py (WACC via CAPM, ROE/ROCE/ROIC/DuPont), not by
# running the code under test.

_INCOME = {
    "date": "2024-12-31",
    "netIncome": 200.0,
    "revenue": 1000.0,
    "incomeBeforeTax": 250.0,
    "interestExpense": 50.0,
    "interestIncome": 0.0,
    "weightedAverageShsOutDil": 100.0,
    "epsDiluted": 2.0,
    "incomeTaxExpense": 52.5,
}
_BALANCE = {
    "date": "2024-12-31",
    "totalAssets": 2000.0,
    "totalEquity": 800.0,
    "totalCurrentLiabilities": 600.0,
    "shortTermDebt": 100.0,
    "longTermDebt": 1900.0,
    "capitalLeaseObligationsCurrent": 0.0,
    "capitalLeaseObligationsNonCurrent": 0.0,
    "cashAndShortTermInvestments": 150.0,
    "totalDebt": 2000.0,  # raw FMP field, read directly by get_wacc()
}
_CASH = {"date": "2024-12-31", "netDividendsPaid": -40.0, "operatingCashFlow": 300.0}

_PROFILE = {"beta": 1.2, "market_cap": 5000.0, "industry": "Software - Application"}
_RATE_ENV = {"latest_value": 4.0}


def _patch_dependencies(monkeypatch):
    async def fake_get_company_profile(symbol):
        return _PROFILE

    async def fake_get_rate_environment():
        return _RATE_ENV

    def fake_fmp_get(endpoint, *, symbol=None, period=None, limit=None, **kwargs):
        return {
            "income-statement": [_INCOME],
            "balance-sheet-statement": [_BALANCE],
            "cash-flow-statement": [_CASH],
        }[endpoint]

    monkeypatch.setattr(capital_efficiency, "get_company_profile", fake_get_company_profile)
    monkeypatch.setattr(capital_efficiency, "get_rate_environment", fake_get_rate_environment)
    monkeypatch.setattr(capital_efficiency, "fmp_get", fake_fmp_get)


async def test_get_wacc_capm_formula(monkeypatch):
    _patch_dependencies(monkeypatch)
    result = await capital_efficiency.get_wacc("TEST")
    # cost_of_equity = 0.04 + 1.2*0.055 = 0.106 -> 10.6%
    # cost_of_debt_after_tax = (50/2000)*(1 - 52.5/250) = 0.025*0.79 = 0.01975 -> 1.98%
    # wacc = (5000/7000)*0.106 + (2000/7000)*0.01975 = 0.0814 -> 8.14%
    assert result["cost_of_equity"] == 10.6
    assert result["cost_of_debt_after_tax"] == 1.98
    assert result["wacc"] == 8.14


async def test_get_capital_efficiency_ratios(monkeypatch):
    _patch_dependencies(monkeypatch)
    result = await capital_efficiency.get_capital_efficiency("TEST")

    assert result["wacc_pct"] == 8.14
    assert result["roe_pct"] == 25.0  # 200/800
    assert result["roce_pct"] == 21.43  # EBIT 300 / capital employed 1400
    assert result["roic_pct"] == 8.94  # NOPAT 237/ invested capital 2650
    assert result["eva"] == 21.29
    assert result["invested_capital"] == 2650.0
    assert result["capital_employed"] == 1400.0

    dupont3 = result["dupont_3factor"]
    assert dupont3["net_margin_pct"] == 20.0
    assert dupont3["asset_turnover"] == 0.5
    assert dupont3["financial_leverage"] == 2.5

    dupont5 = result["dupont_5factor"]
    assert dupont5["tax_burden"] == 0.8
    assert dupont5["interest_burden"] == 0.833
    assert dupont5["operating_margin_pct"] == 30.0


async def test_get_capital_efficiency_rore_needs_five_years(monkeypatch):
    # Only one period of history is supplied, so RORE (a 5-year metric) must
    # stay None rather than divide by an incomplete series.
    _patch_dependencies(monkeypatch)
    result = await capital_efficiency.get_capital_efficiency("TEST")
    assert result["rore_pct"] is None


async def test_get_capital_efficiency_skips_roic_for_bank(monkeypatch):
    monkeypatch.setattr(capital_efficiency, "fmp_get", lambda endpoint, **kw: {
        "income-statement": [_INCOME],
        "balance-sheet-statement": [_BALANCE],
        "cash-flow-statement": [_CASH],
    }[endpoint])

    async def fake_bank_profile(symbol):
        return {**_PROFILE, "industry": "Banks - Regional"}

    async def fake_get_rate_environment():
        return _RATE_ENV

    monkeypatch.setattr(capital_efficiency, "get_company_profile", fake_bank_profile)
    monkeypatch.setattr(capital_efficiency, "get_rate_environment", fake_get_rate_environment)

    result = await capital_efficiency.get_capital_efficiency("TEST")
    assert result["roic_pct"] is None
    assert result["roce_pct"] == 21.43  # ROCE/DuPont still computed for banks
