from agentic.tools.risk_modeling import run_monte_carlo_var
from tests.conftest import FakeDataProvider


def _constant_return_history(daily_return: float, days: int = 35) -> list[dict]:
    """Synthetic price history where every day moves by the same %. Since
    every resampled daily return is identical, the Monte Carlo simulation's
    output is deterministic regardless of RNG draw -- no seeding needed.
    """
    price = 100.0
    history = [{"close": price}]
    for _ in range(days - 1):
        price *= 1 + daily_return
        history.append({"close": price})
    return history


async def test_run_monte_carlo_var_constant_positive_return_is_deterministic():
    # cumulative_return = (1 + 0.01)^21 - 1 = 0.232392... -> 23.24%
    provider = FakeDataProvider(history=_constant_return_history(0.01))
    result = await run_monte_carlo_var(provider, "TEST", confidence=0.95)
    assert result["var_pct"] == 23.24
    assert result["cvar_pct"] == 23.24
    assert result["simulations"] == 10_000
    assert result["horizon_days"] == 21


async def test_run_monte_carlo_var_constant_negative_return_is_deterministic():
    # cumulative_return = (1 - 0.01)^21 - 1 = -0.190259... -> -19.03%
    provider = FakeDataProvider(history=_constant_return_history(-0.01))
    result = await run_monte_carlo_var(provider, "TEST", confidence=0.95)
    assert result["var_pct"] == -19.03
    assert result["cvar_pct"] == -19.03


async def test_run_monte_carlo_var_insufficient_history_returns_none():
    provider = FakeDataProvider(history=_constant_return_history(0.01, days=10))
    result = await run_monte_carlo_var(provider, "TEST")
    assert result["var_pct"] is None
    assert result["cvar_pct"] is None
    assert result["simulations"] == 0
