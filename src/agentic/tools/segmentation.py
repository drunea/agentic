"""Revenue segmentation — by product/business line and by geographic
market — from FMP's `revenue-product-segmentation`/`revenue-geographic-
segmentation` endpoints.

This data has two distinct, unpredictable reliability problems, not just
one:
1. **Undercounting** — segments don't sum to actual total revenue. This
   can vary by company and by endpoint (product vs. geographic) for the
   same company, with no predictable pattern.
2. **Overcounting** — segments sum to *more* than actual revenue, traced to
   FMP sometimes reporting both a parent category (e.g. "Core Banking
   Activities") and its own sub-categories (e.g. "Traditional Banking") as
   siblings in the same flat `data` dict — summing all of them
   double-counts. No residual "Unallocated" row is added to compensate (it
   would read as a normal category and be actively misleading when
   negative — looks like negative revenue). Instead, the *year* is flagged
   as unreliable in both directions and the raw segment numbers stand as
   reported, uncorrected.

Default window is 8 years, not the 15 used elsewhere — segment category
*names* themselves drift over time as companies restructure their
reporting categories, so a longer window mostly adds sparse, mostly-empty
rows for defunct category names rather than useful history.

`limit`/`period` params are silently ignored by these endpoints (passing
them doesn't error, but doesn't limit the response either), so the full
history is always fetched and sliced to `years` here instead.
"""

import asyncio

from agentic.data.fmp_client import fmp_get

_RECONCILE_TOLERANCE = 0.01  # 1% of actual revenue, either direction


async def _get_segmentation_table(symbol: str, endpoint: str, years: int) -> dict:
    seg_raw, income_raw = await asyncio.gather(
        asyncio.to_thread(fmp_get, endpoint, symbol=symbol),
        asyncio.to_thread(fmp_get, "income-statement", symbol=symbol, period="annual"),
    )
    revenue_by_date = {r["date"]: r.get("revenue") for r in income_raw}

    seg_raw = sorted(seg_raw, key=lambda r: r["date"])[-years:]
    if not seg_raw:
        return {"fiscal_years": [], "rows": [], "has_data": False, "unreliable_years": []}

    unreliable_years: list[dict] = []
    fiscal_years = []
    for r in seg_raw:
        fy_label = f"FY {r.get('fiscalYear') or r['date'][:4]}"
        actual = revenue_by_date.get(r["date"])
        seg_sum = sum(r["data"].values())
        flagged = False
        if actual and actual != 0:
            gap = actual - seg_sum
            if abs(gap) / actual > _RECONCILE_TOLERANCE:
                flagged = True
                direction = "below" if gap > 0 else "above"
                unreliable_years.append(
                    {
                        "fiscal_year": fy_label,
                        "reason": f"reported segments sum {direction} actual total revenue by "
                        f"${abs(gap):,.0f} — {'incomplete segmentation' if gap > 0 else 'categories likely overlap (a parent + its own sub-category both counted)'}",
                    }
                )
        fiscal_years.append({"label": fy_label + (" *" if flagged else ""), "date": r["date"], "is_estimate": False})

    # Union of every segment name seen across the displayed window, ordered
    # by size in the most recent year (largest first) so the table reads
    # top-to-bottom by current importance, not alphabetically.
    latest_data = seg_raw[-1]["data"]
    all_segment_names: set[str] = set()
    for r in seg_raw:
        all_segment_names.update(r["data"].keys())
    segment_names = sorted(all_segment_names, key=lambda name: -(latest_data.get(name) or -1))

    rows = [
        {
            "label": name,
            "is_bold": False,
            "is_subheader": False,
            "indent": 0,
            "format_type": "millions",
            "tooltip": None,
            "values": [r["data"].get(name) for r in seg_raw],
        }
        for name in segment_names
    ]

    rows.append(
        {
            "label": "Total Revenue",
            "is_bold": True,
            "is_subheader": True,
            "indent": 0,
            "format_type": "millions",
            "tooltip": "From the Income Statement — compare against the segment rows above. Years "
            "marked with * don't reconcile (segments over- or under-count actual revenue) — see caveats.",
            "values": [revenue_by_date.get(r["date"]) for r in seg_raw],
        }
    )

    return {
        "fiscal_years": fiscal_years,
        "rows": rows,
        "has_data": True,
        "unreliable_years": unreliable_years,
    }


async def get_product_segmentation(symbol: str, years: int = 8) -> dict:
    return await _get_segmentation_table(symbol, "revenue-product-segmentation", years)


async def get_geographic_segmentation(symbol: str, years: int = 8) -> dict:
    return await _get_segmentation_table(symbol, "revenue-geographic-segmentation", years)
