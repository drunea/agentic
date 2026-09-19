from agentic.rag import store
from agentic.rag.embeddings import embed_query


def search_filings(symbol: str, query: str, n_results: int = 5) -> list[dict]:
    """Semantic search over `symbol`'s ingested SEC filings for passages
    matching `query`. Returns [] if nothing has been ingested for `symbol` yet.
    """
    embedding = embed_query(query)
    result = store.query(query_embedding=embedding, symbol=symbol, n_results=n_results)

    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]

    return [
        {"text": doc, "metadata": meta, "distance": dist}
        for doc, meta, dist in zip(documents[0], metadatas[0], distances[0])
    ]
