from agentic.data.base import DataProvider

DEFAULT_WACC = 0.09
DEFAULT_GROWTH = 0.03


async def run_dcf_lite(provider: DataProvider, symbol: str) -> dict:
    """Single-stage Gordon-growth DCF from FCF/share, with fixed WACC/growth
    assumptions. Placeholder for the 3-scenario + sensitivity-matrix DCF
    planned for a later phase.
    """
    fundamentals = await provider.get_fundamentals(symbol)
    fcf_per_share = fundamentals.get("fcf_per_share")

    fair_value = None
    if fcf_per_share:
        fair_value = round(
            (fcf_per_share * (1 + DEFAULT_GROWTH)) / (DEFAULT_WACC - DEFAULT_GROWTH), 2
        )

    return {
        "fair_value_per_share": fair_value,
        "wacc": DEFAULT_WACC,
        "growth_rate": DEFAULT_GROWTH,
    }
