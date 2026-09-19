import chromadb

from agentic.config import settings

_COLLECTION_NAME = "sec_filings"
_client = None


def _get_collection():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client.get_or_create_collection(_COLLECTION_NAME)


def add_chunks(
    *,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict],
) -> None:
    _get_collection().add(
        ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
    )


def has_filings(symbol: str) -> bool:
    return bool(_get_collection().get(where={"symbol": symbol}, limit=1)["ids"])


def query(*, query_embedding: list[float], symbol: str, n_results: int = 5) -> dict:
    return _get_collection().query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={"symbol": symbol},
    )
