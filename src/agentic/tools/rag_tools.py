import asyncio

from agentic.rag import store
from agentic.rag.ingest import ingest_filing
from agentic.rag.retriever import search_filings

# Keep the tool's return small: a full ~3200-char stored chunk is plenty for
# a citation snippet, but 5 of them pushed a prompt past the model's context
# window (see llm.py's _OLLAMA_NUM_CTX comment) and caused a 50+ minute hang.
_MAX_RESULTS = 3
_MAX_EXCERPT_CHARS = 600

# Valuation and Disruption run concurrently in one refresh and both call
# `ensure_filings_ingested` — without this, both would see "nothing ingested"
# and download/embed the same 10-K twice.
_ingest_locks: dict[str, asyncio.Lock] = {}

# Ollama embeds one request at a time, so ingesting several symbols in
# parallel doesn't finish sooner — it only makes every other embedding call
# (including the query embedding every Valuation/Disruption run needs) wait
# behind all of them. One ingest at a time keeps that wait to a single batch.
_ingest_slot = asyncio.Semaphore(1)


async def ensure_filings_ingested(symbol: str) -> str | None:
    """Ingests `symbol`'s latest 10-K into the RAG store if none is there
    yet, so filing citations appear for any symbol rather than only ones
    someone ran `python -m agentic.rag.ingest` for by hand. Best-effort:
    returns a caveat string on failure (missing SEC contact email, no 10-K
    on EDGAR, Ollama embed model down...) instead of raising — a specialist
    must still produce its numbers without filing excerpts.
    """
    lock = _ingest_locks.setdefault(symbol, asyncio.Lock())
    async with lock:
        try:
            if await asyncio.to_thread(store.has_filings, symbol):
                return None
            async with _ingest_slot:
                chunks = await asyncio.to_thread(ingest_filing, symbol)
        except Exception as exc:  # noqa: BLE001
            return f"Could not ingest SEC filings for {symbol}: {exc}"
    return None if chunks else f"No 10-K found on SEC EDGAR for {symbol}."


async def search_filings_tool(symbol: str, query: str) -> list[dict]:
    """Semantic search over `symbol`'s ingested SEC filings. Returns [] if
    nothing has been ingested for the symbol yet (see
    `ensure_filings_ingested`) — callers should treat that as "no citations
    available", not an error.
    """
    # In a thread: the query embedding is a blocking HTTP call to Ollama that
    # took 50s+ while other symbols were ingesting — on the event loop that
    # froze every API request for that long.
    results = await asyncio.to_thread(search_filings, symbol, query, n_results=_MAX_RESULTS)
    return [
        {"text": r["text"][:_MAX_EXCERPT_CHARS], "metadata": r["metadata"]} for r in results
    ]
