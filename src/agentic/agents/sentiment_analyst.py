from pydantic_ai import Agent, RunContext

from agentic.agents.base import AgentDeps
from agentic.data.base import DataProvider
from agentic.llm import get_model
from agentic.schemas.sentiment import Headline, SentimentReport
from agentic.tools.news_sentiment import get_news_sentiment

sentiment_agent = Agent(
    get_model("sentiment"),
    deps_type=AgentDeps,
    output_type=SentimentReport,
    retries={"output": 3, "tools": 3},
    system_prompt=(
        "You are a news sentiment analyst. Call the news sentiment tool for "
        "the given symbol, then copy its average_score and article_count "
        "EXACTLY into the matching output fields, and its headlines list into "
        "`headlines` — never leave these null/empty if the tool returned "
        "values. Classify `tone` as 'positive', 'negative', or 'neutral' "
        "based on the average VADER score (>0.05 positive, <-0.05 negative, "
        "otherwise neutral). Lower `confidence` if article_count is low. "
        "Respond ONLY with the required structured output — never plain "
        "prose."
    ),
)


@sentiment_agent.tool
async def news_sentiment(ctx: RunContext[AgentDeps], symbol: str) -> dict:
    """Average VADER sentiment score over recent headlines for `symbol`."""
    return await get_news_sentiment(ctx.deps.provider, symbol)


def _classify_tone(average_score: float | None) -> str:
    """Same threshold rule the system prompt asks the LLM to apply — kept
    here too so `tone` can be recomputed independently of whether the LLM
    got it right (see `analyze_sentiment` below).
    """
    if average_score is None:
        return "neutral"
    if average_score > 0.05:
        return "positive"
    if average_score < -0.05:
        return "negative"
    return "neutral"


async def analyze_sentiment(provider: DataProvider, symbol: str) -> SentimentReport:
    """Bridge to the orchestration layer — Sentiment is not yet converted to
    the zero/single-LLM-call pattern used elsewhere, still an agentic
    tool-loop. Kept as its own thin wrapper so orchestration.py doesn't need
    to special-case Agent-vs-plain-function per specialist.
    """
    result = await sentiment_agent.run(
        f"Perform a news sentiment analysis of {symbol}.",
        deps=AgentDeps(provider=provider),
    )
    # `average_score`/`article_count`/`headlines`/`data_source` are all
    # plain VADER/tool output with no judgment for the LLM to add — the
    # system prompt asks it to "copy exactly", but llm.py's own model-choice
    # notes record two local models that failed exactly that: one nulled
    # tool-result fields, the other fabricated plausible-looking wrong
    # numbers instead. Rather than trust the transcription (and only find
    # out from a bad report if a future model/Ollama upgrade regresses the
    # same way), every one of these is set directly from the authoritative
    # tool call — the LLM's own copies are discarded, not just checked.
    # `tone` is a fixed threshold rule on `average_score` (see the system
    # prompt), so it's recomputed the same way rather than trusted either.
    authoritative = await get_news_sentiment(provider, symbol)
    result.output.average_score = authoritative.get("average_score")
    result.output.article_count = authoritative.get("article_count", 0)
    result.output.tone = _classify_tone(result.output.average_score)
    result.output.headlines = [
        Headline(**h) for h in authoritative["headlines"]
    ]
    result.output.data_source = authoritative.get("data_source", "")
    return result.output
