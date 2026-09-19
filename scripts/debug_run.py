"""Debug helper for the company_analysis architecture (2026-09-15) — runs
every specialist for a symbol directly, no HTTP/DB polling, and prints each
one's status/result as it completes.
"""

import asyncio
import os
import sys

os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

from agentic.data.chain import ProviderChain
from agentic.orchestration import SPECIALISTS


async def main(symbol: str) -> None:
    provider = ProviderChain()
    for name, fn in SPECIALISTS.items():
        print(f"--- {name} ---")
        try:
            report = await fn(provider, symbol)
            print(report.model_dump_json(indent=2))
        except Exception as exc:  # noqa: BLE001 - debug script, show the failure and keep going
            print(f"FAILED: {exc}")
        print()


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    asyncio.run(main(symbol))
