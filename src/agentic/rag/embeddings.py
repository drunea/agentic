"""Embeddings via Ollama's native /api/embed — keeps RAG on the same local
daemon already used for chat, no extra service.

If retrieval quality ever proves insufficient, swap in a `sentence-transformers`
backend behind this same `embed_texts` signature — not implemented now since
nothing has shown a need for it yet.
"""

import httpx

from agentic.config import settings


# One request per batch, not per call: all of a large 10-K's chunks in a
# single request exceeded the 120s timeout.
_EMBED_BATCH_SIZE = 32


def embed_texts(texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        response = httpx.post(
            f"{settings.ollama_native_base_url}/api/embed",
            json={"model": settings.ollama_embed_model, "input": texts[start : start + _EMBED_BATCH_SIZE]},
            timeout=120,
        )
        response.raise_for_status()
        embeddings.extend(response.json()["embeddings"])
    return embeddings


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
