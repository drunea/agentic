from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from agentic.data.base import DataProvider

_analyzer = SentimentIntensityAnalyzer()


async def get_news_sentiment(provider: DataProvider, symbol: str, limit: int = 20) -> dict:
    """VADER compound sentiment score averaged over recent headlines."""
    news = await provider.get_news(symbol, limit=limit)

    scores = []
    headlines = []
    for item in news:
        title = item.get("title", "")
        if not title:
            continue
        scores.append(_analyzer.polarity_scores(title)["compound"])
        headlines.append({"title": title, "url": item.get("url"), "site": item.get("site")})

    return {
        "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        "article_count": len(scores),
        "headlines": headlines[:5],
        "data_source": news[0].get("_provider", "") if news else "",
    }
