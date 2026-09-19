import asyncio

import httpx

from agentic.config import settings

# DGS10 = 10-Year Treasury Constant Maturity Rate — a standard proxy for the
# risk-free rate / broad rate environment.
_DEFAULT_SERIES = "DGS10"


async def get_rate_environment(series_id: str = _DEFAULT_SERIES) -> dict:
    """Latest and prior value of a FRED macro series (default: 10Y Treasury yield)."""
    return await asyncio.to_thread(_get_rate_environment_sync, series_id)


def _get_rate_environment_sync(series_id: str) -> dict:
    if not settings.fred_api_key:
        return {"series_id": series_id, "latest_value": None, "previous_value": None}

    response = httpx.get(
        settings.fred_base_url,
        params={
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 10,
        },
        timeout=10,
    )
    response.raise_for_status()
    observations = response.json().get("observations", [])
    # FRED uses "." for non-trading days (weekends/holidays) instead of omitting the row.
    values = [
        (obs["date"], float(obs["value"])) for obs in observations if obs["value"] != "."
    ]

    return {
        "series_id": series_id,
        "latest_date": values[0][0] if values else None,
        "latest_value": values[0][1] if values else None,
        "previous_value": values[1][1] if len(values) > 1 else None,
    }
