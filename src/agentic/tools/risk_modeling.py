import numpy as np
import pandas as pd

from agentic.data.base import DataProvider

N_SIMULATIONS = 10_000
HORIZON_DAYS = 21  # ~1 trading month


async def run_monte_carlo_var(
    provider: DataProvider, symbol: str, confidence: float = 0.95
) -> dict:
    """Historical-simulation Monte Carlo VaR/CVaR: resamples historical daily
    returns (with replacement) into `N_SIMULATIONS` simulated `HORIZON_DAYS`-day
    paths, then reads the loss distribution's tail. `var_pct`/`cvar_pct` are
    negative percentages (e.g. -8.5 means an 8.5% loss).
    """
    history = await provider.get_history(symbol, period="1y")
    data_source = history[0].get("_provider", "") if history else ""
    if len(history) < 30:
        return {
            "var_pct": None,
            "cvar_pct": None,
            "confidence_level": confidence,
            "horizon_days": HORIZON_DAYS,
            "simulations": 0,
            "data_source": data_source,
        }

    df = pd.DataFrame(history)
    df.columns = [str(c).lower() for c in df.columns]
    closes = df["close"].astype(float).to_numpy()
    daily_returns = np.diff(closes) / closes[:-1]

    rng = np.random.default_rng()
    sampled = rng.choice(daily_returns, size=(N_SIMULATIONS, HORIZON_DAYS), replace=True)
    cumulative_returns = np.prod(1 + sampled, axis=1) - 1

    var_pct = float(np.percentile(cumulative_returns, (1 - confidence) * 100))
    tail = cumulative_returns[cumulative_returns <= var_pct]
    cvar_pct = float(tail.mean()) if len(tail) else var_pct

    return {
        "var_pct": round(var_pct * 100, 2),
        "cvar_pct": round(cvar_pct * 100, 2),
        "confidence_level": confidence,
        "horizon_days": HORIZON_DAYS,
        "simulations": N_SIMULATIONS,
        "data_source": data_source,
    }
