from agentic.rag import embeddings


class _FakeResponse:
    def __init__(self, inputs):
        self._inputs = inputs

    def raise_for_status(self):
        pass

    def json(self):
        return {"embeddings": [[float(text)] for text in self._inputs]}


def test_embed_texts_batches_requests_and_preserves_order(monkeypatch):
    batch_sizes = []

    def fake_post(url, json, timeout):
        batch_sizes.append(len(json["input"]))
        return _FakeResponse(json["input"])

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    texts = [str(i) for i in range(70)]
    result = embeddings.embed_texts(texts)

    assert batch_sizes == [32, 32, 6]
    assert result == [[float(i)] for i in range(70)]
