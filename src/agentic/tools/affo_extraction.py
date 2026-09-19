"""FFO/AFFO reconciliation-table extraction from a REIT's 10-K filings.

Deliberately NOT reusing `rag/ingest.py`'s pipeline beyond the SEC EDGAR
download step: that pipeline flattens the whole filing to plain text
(`chunking.py::html_to_text`) for embedding-based semantic search, which
destroys a table's row/column alignment — exactly the structure needed here
(a number is meaningless without knowing which row/year it belongs to).
Instead: download the filing, find the specific reconciliation table with
BeautifulSoup, and hand its row-by-row text directly to an LLM for
structured extraction — no chunking, no embeddings, no vector store.

A formula computed from FMP's raw statement lines would be a
confident-looking approximation with real error (no field splits
maintenance vs. growth CapEx, no field for gains-on-sale or straight-line
rent). The company's own reported reconciliation is the accurate source —
REITs each compute AFFO slightly differently, which is exactly why they
publish this table themselves.

Supports fetching a specific filing via `before` (SEC EDGAR's own date
filter) — not just "the latest" — because a single 10-K only covers ~2-3
fiscal years, and `agents/affo_analyst.py` walks backward through older
filings across successive refreshes to build up more history over time
rather than re-fetching the same latest filing forever.
"""

from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
from sec_edgar_downloader import Downloader

from agentic.config import settings
from agentic.rag.ingest import _extract_filed_date

_DOWNLOAD_ROOT = Path("sec_filings")
# Not every REIT calls this "AFFO" — e.g. Alexandria Real Estate (ARE)
# reports "Funds From Operations ... As Adjusted" and never uses the
# literal string "AFFO" in its actual reconciliation table.
_TABLE_KEYWORDS = (
    "AFFO",
    "ADJUSTED FUNDS FROM OPERATIONS",
    "FFO AS ADJUSTED",
    "FFO, AS ADJUSTED",
    "AS ADJUSTED",  # catches "...Diluted, As Adjusted" table headers like ARE's, without requiring "FFO" adjacent
    "NORMALIZED FFO",
    "CORE FFO",
    "CASH AVAILABLE FOR DISTRIBUTION",
    "FUNDS AVAILABLE FOR DISTRIBUTION",
    "FUNDS FROM OPERATIONS",
)


def _has_net_income_anchor(text_upper: str) -> bool:
    """Not a literal "NET INCOME" substring check — some filings (e.g. ARE)
    read "NET (LOSS) INCOME ATTRIBUTABLE TO...", which contains neither
    "NET INCOME" nor "NET LOSS" as one contiguous phrase. "NET" + either
    "INCOME" or "LOSS" present anywhere in the table (not necessarily
    adjacent) is looser but still precise enough combined with the
    metric-keyword check above — an unrelated table matching both checks by
    coincidence is unlikely.
    """
    return "NET" in text_upper and ("INCOME" in text_upper or "LOSS" in text_upper)


def _table_to_text(table) -> str:
    lines = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _find_reconciliation_table(html: str) -> str | None:
    """Collects every matching table, not just the first — some filings
    (e.g. ARE) report the dollar-amount reconciliation and the per-share
    reconciliation as two separate tables; returning only the first match
    would silently drop whichever one comes second (per-share is what the
    schema actually needs — `affo_per_share` — so dropping it would defeat
    the point).
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    for table in soup.find_all("table"):
        text = table.get_text(separator=" ", strip=True).upper()
        if _has_net_income_anchor(text) and any(kw in text for kw in _TABLE_KEYWORDS):
            table_text = _table_to_text(table)
            if table_text and table_text not in matches:
                matches.append(table_text)
    if not matches:
        return None
    return "\n\n---\n\n".join(matches)


def get_affo_reconciliation_text(symbol: str, before: str | None = None) -> tuple[str, str] | None:
    """Downloads a 10-K (the latest one, or the latest filed *before* the
    given YYYY-MM-DD date) and returns `(reconciliation_table_text,
    filed_date)`, or None if no filing or no matching table was found.
    Synchronous (network + disk I/O) — callers run this via
    `asyncio.to_thread`, same convention as `rag/ingest.py::ingest_filing`.

    Doesn't trust "the newest accession directory on disk" to mean "the one
    just requested" — `sec_edgar_downloader` never deletes previously
    downloaded filings, so a symbol refreshed multiple times (walking
    backward through its filing history across sessions) accumulates
    several different 10-Ks side by side. Instead: read every cached
    filing's own "FILED AS OF DATE" header and pick the one that actually
    matches the request (latest overall, or latest still `< before`).
    """
    if not settings.sec_edgar_contact_email:
        raise RuntimeError(
            "SEC_EDGAR_CONTACT_EMAIL is not set — SEC EDGAR requires a contact "
            "email in the download User-Agent."
        )

    # `sec_edgar_downloader`'s own `before` is INCLUSIVE — with `before` set
    # to the exact date of a filing already on file, it returns that same
    # filing instead of the one before it (walking backward would silently
    # make zero progress). Shifting by one day makes the caller's "before
    # this filing" mean what it says.
    query_before = None
    if before is not None:
        query_before = (date.fromisoformat(before) - timedelta(days=1)).isoformat()

    downloader = Downloader(settings.sec_edgar_company_name, settings.sec_edgar_contact_email, _DOWNLOAD_ROOT)
    downloader.get("10-K", symbol, limit=1, before=query_before, download_details=True)

    filing_dir = _DOWNLOAD_ROOT / "sec-edgar-filings" / symbol / "10-K"
    if not filing_dir.exists():
        return None

    candidates: list[tuple[str, Path]] = []
    for accession_dir in filing_dir.iterdir():
        full_submission = accession_dir / "full-submission.txt"
        if not full_submission.exists():
            continue
        filed_date = _extract_filed_date(full_submission)
        if not filed_date:
            continue
        if query_before is not None and filed_date > query_before:
            continue
        candidates.append((filed_date, accession_dir))

    if not candidates:
        return None
    filed_date, accession_dir = max(candidates, key=lambda c: c[0])

    primary_doc = accession_dir / "primary-document.html"
    if not primary_doc.exists():
        return None

    html = primary_doc.read_text(encoding="utf-8", errors="ignore")
    table_text = _find_reconciliation_table(html)
    if table_text is None:
        return None
    return table_text, filed_date
