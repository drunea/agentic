from agentic.tools.valuation import run_dcf_lite
from tests.conftest import FakeDataProvider


async def test_run_dcf_lite_gordon_growth_formula():
    # fair_value = fcf_per_share * (1 + growth) / (wacc - growth)
    #            = 5 * 1.03 / 0.06 = 85.8333... -> 85.83
    provider = FakeDataProvider(fundamentals={"fcf_per_share": 5})
    result = await run_dcf_lite(provider, "TEST")
    assert result["fair_value_per_share"] == 85.83
    assert result["wacc"] == 0.09
    assert result["growth_rate"] == 0.03


async def test_run_dcf_lite_missing_fcf_is_none():
    provider = FakeDataProvider(fundamentals={"fcf_per_share": None})
    result = await run_dcf_lite(provider, "TEST")
    assert result["fair_value_per_share"] is None


async def test_run_dcf_lite_zero_fcf_is_none():
    provider = FakeDataProvider(fundamentals={"fcf_per_share": 0})
    result = await run_dcf_lite(provider, "TEST")
    assert result["fair_value_per_share"] is None
