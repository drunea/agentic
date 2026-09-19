import agentic.agents.sentiment_analyst as sentiment_analyst
from agentic.schemas.sentiment import Headline, SentimentReport
from tests.conftest import FakeDataProvider


def test_classify_tone_positive():
    assert sentiment_analyst._classify_tone(0.5) == "positive"


def test_classify_tone_negative():
    assert sentiment_analyst._classify_tone(-0.5) == "negative"


def test_classify_tone_neutral_at_and_near_zero():
    assert sentiment_analyst._classify_tone(0.0) == "neutral"
    assert sentiment_analyst._classify_tone(0.05) == "neutral"  # boundary: not > 0.05


def test_classify_tone_none_is_neutral():
    assert sentiment_analyst._classify_tone(None) == "neutral"


class _FakeAgentResult:
    def __init__(self, output):
        self.output = output


async def test_analyze_sentiment_overrides_llm_transcription_with_authoritative_values(monkeypatch):
    # Reproduces exactly the regression llm.py's model-choice notes warn
    # about: the LLM "copies" average_score/article_count wrong (nulled or
    # fabricated) and, as a result, mislabels tone too. analyze_sentiment
    # must discard all of this in favor of the authoritative VADER tool
    # result, not trust the LLM's transcription of it.
    wrong_output = SentimentReport(
        symbol="TEST",
        confidence=0.9,
        caveats=[],
        data_source="wrong",
        average_score=None,  # LLM nulled it
        article_count=999,  # LLM fabricated it
        tone="negative",  # wrong given the real average_score below
        headlines=[Headline(title="wrong headline", url=None, site=None)],
        summary="a summary",
    )

    async def fake_run(prompt, deps=None):
        return _FakeAgentResult(wrong_output)

    async def fake_get_news_sentiment(provider, symbol):
        return {
            "average_score": 0.42,
            "article_count": 7,
            "headlines": [{"title": "real headline", "url": "http://x", "site": "Reuters"}],
            "data_source": "massive",
        }

    monkeypatch.setattr(sentiment_analyst.sentiment_agent, "run", fake_run)
    monkeypatch.setattr(sentiment_analyst, "get_news_sentiment", fake_get_news_sentiment)

    result = await sentiment_analyst.analyze_sentiment(FakeDataProvider(), "TEST")

    assert result.average_score == 0.42
    assert result.article_count == 7
    assert result.tone == "positive"  # recomputed from 0.42, not trusted from the LLM's "negative"
    assert result.headlines[0].title == "real headline"
    assert result.data_source == "massive"
    assert result.summary == "a summary"  # untouched -- genuine LLM content, not overridden
