"""Shared plumbing for specialists that turn retrieved SEC filing excerpts
into cited insights: the excerpts go into the prompt numbered, the LLM points
at one by number per insight, and the filing type/date/excerpt shown to the
user are looked up here from that number — not trusted from the LLM.
"""

from pydantic import BaseModel, Field

from agentic.schemas.common import FilingCitation


class CitedInsight(BaseModel):
    insight: str
    excerpt_number: int = Field(
        description="The [number] of the single filing excerpt this insight is based on."
    )


def format_excerpts(excerpts: list[dict]) -> str:
    blocks = []
    for number, excerpt in enumerate(excerpts, start=1):
        meta = excerpt.get("metadata") or {}
        header = f"[{number}] ({meta.get('filing_type') or 'filing'}, filed {meta.get('filing_date') or 'unknown date'})"
        blocks.append(f"{header}\n{excerpt['text']}")
    return "\n---\n".join(blocks)


def resolve_citations(
    cited: list[CitedInsight], excerpts: list[dict]
) -> tuple[list[FilingCitation], int]:
    """Returns `(citations, dropped)`. An insight pointing at an excerpt
    number that doesn't exist can't be sourced, so it's dropped rather than
    shown unsourced — the same "discard, don't guess" rule as AFFO's checks.
    """
    resolved: list[FilingCitation] = []
    dropped = 0
    for item in cited:
        if not 1 <= item.excerpt_number <= len(excerpts):
            dropped += 1
            continue
        excerpt = excerpts[item.excerpt_number - 1]
        meta = excerpt.get("metadata") or {}
        resolved.append(
            FilingCitation(
                insight=item.insight,
                filing_type=meta.get("filing_type") or "",
                filing_date=meta.get("filing_date") or "",
                excerpt=excerpt["text"],
            )
        )
    return resolved, dropped
