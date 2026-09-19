import asyncio

from agentic.data.base import DataProvider
from agentic.data.fmp_client import fmp_get
from agentic.tools.financial_metrics import get_valuation_ratios

_MAX_COMPARED_PEERS = 5


async def find_peers(symbol: str) -> list[str]:
    """Peer tickers for `symbol`, via FMP's stock-peers endpoint.

    FMP-specific for now (not behind the DataProvider abstraction) since
    only one provider exists today; revisit once a second provider needs to
    offer peer discovery too.
    """
    result = await asyncio.to_thread(fmp_get, "stock-peers", symbol=symbol)
    return [item["symbol"] for item in result] if isinstance(result, list) else []


async def get_peer_comparison(provider: DataProvider, peers: list[str]) -> list[dict]:
    """Same core valuation ratios as the main report, computed for each of
    the (up to 5) peer tickers, so a peer list is an actual comparison table
    instead of just names with no context.
    """
    comparisons = []
    for peer_symbol in peers[:_MAX_COMPARED_PEERS]:
        ratios = await get_valuation_ratios(provider, peer_symbol)
        comparisons.append(
            {
                "symbol": peer_symbol,
                "pe_ratio": ratios.get("pe_ratio"),
                "pb_ratio": ratios.get("pb_ratio"),
                "roe": ratios.get("roe"),
            }
        )
    return comparisons
