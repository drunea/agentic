from agentic.tools.financial_statements import (
    ebit,
    ebitda,
    growth,
    net_debt_computed,
    safe_div,
    total_financial_debt,
)


def test_safe_div_normal():
    assert safe_div(10, 4) == 2.5


def test_safe_div_zero_denominator_is_none():
    assert safe_div(10, 0) is None


def test_safe_div_missing_operand_is_none():
    assert safe_div(None, 5) is None
    assert safe_div(5, None) is None


def test_growth_normal():
    assert growth({"revenue": 120}, {"revenue": 100}, "revenue") == 0.2


def test_growth_no_prior_period_is_none():
    assert growth({"revenue": 120}, None, "revenue") is None


def test_growth_prior_zero_is_none():
    assert growth({"revenue": 120}, {"revenue": 0}, "revenue") is None


def test_ebit_is_ebt_plus_net_interest_expense():
    # EBT 100 + interest expense 20 - interest income 5 = 115
    period = {"incomeBeforeTax": 100, "interestExpense": 20, "interestIncome": 5}
    assert ebit(period) == 115


def test_ebit_missing_field_is_none():
    assert ebit({"incomeBeforeTax": 100}) is None


def test_ebitda_is_ebit_plus_da():
    period = {
        "incomeBeforeTax": 100,
        "interestExpense": 20,
        "interestIncome": 5,
        "depreciationAndAmortization": 30,
    }
    assert ebitda(period) == 145


def test_total_financial_debt_sums_all_four_components():
    balance = {
        "shortTermDebt": 100,
        "capitalLeaseObligationsCurrent": 10,
        "longTermDebt": 300,
        "capitalLeaseObligationsNonCurrent": 40,
    }
    assert total_financial_debt(balance) == 450


def test_net_debt_computed_subtracts_cash_and_sti():
    balance = {
        "shortTermDebt": 100,
        "capitalLeaseObligationsCurrent": 0,
        "longTermDebt": 300,
        "capitalLeaseObligationsNonCurrent": 0,
        "cashAndShortTermInvestments": 150,
    }
    assert net_debt_computed(balance) == 250
