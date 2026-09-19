"""Earnings call transcript analysis — single-LLM-call tier (same category
as AFFO/valuation/disruption/sentiment): one tool-free completion
over pre-fetched text, no tool-calling loop.

Runs on Gemini, not the project's default Ollama backend — a real
transcript runs ~12k tokens, too close to Ollama's 16k context ceiling to
trust with a structured-output call on top. Set via
`EARNINGS_CALL_LLM_BACKEND=gemini` in .env, the same per-agent override
mechanism used for `affo`.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agentic.data.base import DataProvider
from agentic.llm import get_model
from agentic.schemas.earnings_call import EarningsCallReport, EvasiveStatement
from agentic.tools.earnings_call import get_latest_transcript_info, get_transcript_text


class _EarningsCallExtraction(BaseModel):
    management_tone: str
    key_topics: list[str] = Field(default_factory=list)
    evasive_statements: list[EvasiveStatement] = Field(default_factory=list)


_earnings_call_agent = Agent(
    get_model("earnings_call"),
    output_type=_EarningsCallExtraction,
    retries={"output": 3},
    system_prompt=(
        "You are analyzing a company's quarterly earnings call transcript. Read the full "
        "transcript (prepared remarks + Q&A) and extract:\n"
        "1. `management_tone` — one short phrase describing leadership's overall tone on this "
        "call (e.g. confident, cautious, defensive, upbeat, guarded). Base this on actual "
        "language used, not just reported numbers.\n"
        "2. `key_topics` — the main themes/subjects discussed (5-10 short phrases), covering "
        "both prepared remarks and analyst questions.\n"
        "3. `evasive_statements` — specific moments in the Q&A where an executive dodged, "
        "deflected, or gave a vague/non-answer to a direct analyst question. For each: the "
        "analyst's question (if identifiable), a short excerpt/paraphrase of the response, and "
        "why it reads as evasive. Only include genuine cases — do not invent ones. An empty "
        "list is a valid, honest answer if nothing evasive occurred.\n"
        "Respond ONLY with the required structured output — never plain prose."
    ),
)


async def analyze_earnings_call(provider: DataProvider, symbol: str) -> EarningsCallReport:
    info = await get_latest_transcript_info(symbol)
    if info is None:
        return EarningsCallReport(
            symbol=symbol,
            quarter=0,
            year=0,
            call_date=None,
            management_tone="n/a",
            confidence=0.0,
            caveats=["No earnings call transcript available for this symbol."],
            summary=f"{symbol}: no earnings call transcript found.",
        )

    quarter, year, call_date, transcript_provider = info
    transcript = await get_transcript_text(symbol, quarter, year, transcript_provider)
    if not transcript:
        return EarningsCallReport(
            symbol=symbol,
            quarter=quarter,
            year=year,
            call_date=call_date,
            data_source=transcript_provider,
            management_tone="n/a",
            confidence=0.2,
            caveats=[f"Transcript listed for Q{quarter} {year} but its text could not be fetched."],
            summary=f"{symbol}: transcript for Q{quarter} {year} listed but unavailable.",
        )

    llm_result = await _earnings_call_agent.run(
        f"Ticker: {symbol}, Q{quarter} {year} earnings call transcript:\n\n{transcript}"
    )
    extraction = llm_result.output

    caveats = []
    if not extraction.key_topics:
        caveats.append("No key topics extracted.")

    summary = (
        f"{symbol} Q{quarter} {year} earnings call: tone was {extraction.management_tone}. "
        f"{len(extraction.evasive_statements)} potentially evasive response(s) flagged in Q&A. "
        f"Key topics: {', '.join(extraction.key_topics[:5]) or 'none extracted'}."
    )

    return EarningsCallReport(
        symbol=symbol,
        quarter=quarter,
        year=year,
        call_date=call_date,
        data_source=transcript_provider,
        management_tone=extraction.management_tone,
        key_topics=extraction.key_topics,
        evasive_statements=extraction.evasive_statements,
        confidence=1.0 if extraction.key_topics else 0.5,
        caveats=caveats,
        summary=summary,
    )
