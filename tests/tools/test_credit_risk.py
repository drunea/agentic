from agentic.tools.credit_risk import _altman_z_score, _piotroski_f_score

# --- Altman Z-Score -----------------------------------------------------
#
# Z = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 0.999*x5, where
#   x1 = working capital / total assets
#   x2 = retained earnings / total assets
#   x3 = EBIT / total assets
#   x4 = market cap / total liabilities
#   x5 = revenue / total assets


def test_altman_z_score_safe_zone():
    income0 = {"incomeBeforeTax": 100, "interestExpense": 20, "interestIncome": 0, "revenue": 800}
    balance0 = {
        "totalAssets": 1000,
        "totalCurrentAssets": 600,
        "totalCurrentLiabilities": 200,
        "retainedEarnings": 300,
        "totalLiabilities": 500,
    }
    # x1=0.4, x2=0.3, x3=0.12, x4=3.0, x5=0.8
    # Z = 1.2*0.4 + 1.4*0.3 + 3.3*0.12 + 0.6*3.0 + 0.999*0.8 = 3.8952 -> 3.9
    result = _altman_z_score(income0, balance0, market_cap=1500)
    assert result["z_score"] == 3.9
    assert result["zone"] == "safe"


def test_altman_z_score_distress_zone():
    income0 = {"incomeBeforeTax": -150, "interestExpense": 50, "interestIncome": 0, "revenue": 300}
    balance0 = {
        "totalAssets": 1000,
        "totalCurrentAssets": 100,
        "totalCurrentLiabilities": 600,
        "retainedEarnings": -500,
        "totalLiabilities": 1000,
    }
    # x1=-0.5, x2=-0.5, x3=-0.1, x4=0.2, x5=0.3
    # Z = -0.6 - 0.7 - 0.33 + 0.12 + 0.2997 = -1.2103 -> -1.21
    result = _altman_z_score(income0, balance0, market_cap=200)
    assert result["z_score"] == -1.21
    assert result["zone"] == "distress"


def test_altman_z_score_missing_field_returns_none():
    income0 = {"incomeBeforeTax": 100, "interestExpense": 20, "interestIncome": 0, "revenue": 800}
    balance0 = {
        "totalAssets": 1000,
        "totalCurrentAssets": 600,
        "totalCurrentLiabilities": 200,
        "retainedEarnings": None,  # missing -> x2 unknowable
        "totalLiabilities": 500,
    }
    result = _altman_z_score(income0, balance0, market_cap=1500)
    assert result["z_score"] is None
    assert result["zone"] is None
    assert result["components"]["retained_earnings_to_assets"] is None
    assert result["components"]["working_capital_to_assets"] == 0.4


# --- Piotroski F-Score ---------------------------------------------------


def _full_data_periods():
    income0 = {
        "netIncome": 200,
        "grossProfit": 500,
        "revenue": 1000,
        "weightedAverageShsOut": 100,
    }
    income1 = {
        "netIncome": 100,
        "grossProfit": 350,
        "revenue": 800,
        "weightedAverageShsOut": 110,
    }
    balance0 = {
        "totalAssets": 1000,
        "longTermDebt": 200,
        "totalCurrentAssets": 600,
        "totalCurrentLiabilities": 200,
    }
    balance1 = {
        "totalAssets": 1000,
        "longTermDebt": 400,
        "totalCurrentAssets": 500,
        "totalCurrentLiabilities": 300,
    }
    cash0 = {"operatingCashFlow": 250}
    return income0, income1, balance0, balance1, cash0


def test_piotroski_f_score_all_criteria_pass():
    result = _piotroski_f_score(*_full_data_periods())
    assert result["criteria_determined"] == 9
    assert result["f_score"] == 9
    assert all(result["criteria"].values())


def test_piotroski_f_score_excludes_undetermined_criteria():
    income0, income1, balance0, balance1, cash0 = _full_data_periods()
    income1 = {**income1, "weightedAverageShsOut": None}  # can't tell if shares improved

    result = _piotroski_f_score(income0, income1, balance0, balance1, cash0)
    assert result["criteria_determined"] == 8
    assert result["f_score"] == 8
    assert result["criteria"]["no_new_shares_issued"] is None
