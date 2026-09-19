"""Download SEC filings, chunk + embed them, and store in Chroma.

CLI usage:
    python -m agentic.rag.ingest --symbol AAPL [--form 10-K] [--limit 1]
"""

import argparse
import re
from pathlib import Path

from sec_edgar_downloader import Downloader

from agentic.config import settings
from agentic.rag import store
from agentic.rag.chunking import chunk_text, html_to_text
from agentic.rag.embeddings import embed_texts

_DOWNLOAD_ROOT = Path("sec_filings")
_FILED_DATE_RE = re.compile(rb"FILED AS OF DATE:\s*(\d{8})")


def _extract_filed_date(full_submission_path: Path) -> str | None:
    """The SEC header is in the first few KB — no need to read the whole file."""
    with open(full_submission_path, "rb") as f:
        head = f.read(4096)
    match = _FILED_DATE_RE.search(head)
    if not match:
        return None
    raw = match.group(1).decode()
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def ingest_filing(symbol: str, form: str = "10-K", limit: int = 1) -> int:
    """Downloads, chunks, embeds and stores up to `limit` filings of `form`
    type for `symbol`. Returns the number of chunks stored.
    """
    if not settings.sec_edgar_contact_email:
        raise RuntimeError(
            "SEC_EDGAR_CONTACT_EMAIL is not set — SEC EDGAR requires a contact "
            "email in the download User-Agent."
        )

    downloader = Downloader(
        settings.sec_edgar_company_name, settings.sec_edgar_contact_email, _DOWNLOAD_ROOT
    )
    downloader.get(form, symbol, limit=limit, download_details=True)

    filing_dir = _DOWNLOAD_ROOT / "sec-edgar-filings" / symbol / form
    if not filing_dir.exists():
        return 0

    total_chunks = 0
    for accession_dir in sorted(filing_dir.iterdir()):
        primary_doc = accession_dir / "primary-document.html"
        full_submission = accession_dir / "full-submission.txt"
        if not primary_doc.exists():
            continue

        text = html_to_text(primary_doc.read_text(encoding="utf-8", errors="ignore"))
        chunks = chunk_text(text)
        if not chunks:
            continue

        filed_date = _extract_filed_date(full_submission) if full_submission.exists() else None
        embeddings = embed_texts(chunks)
        ids = [f"{symbol}-{form}-{accession_dir.name}-{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "symbol": symbol,
                "filing_type": form,
                "filing_date": filed_date or "",
                "accession": accession_dir.name,
            }
            for _ in chunks
        ]
        store.add_chunks(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
        total_chunks += len(chunks)

    return total_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest SEC filings into the RAG store.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--form", default="10-K")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()

    count = ingest_filing(args.symbol, form=args.form, limit=args.limit)
    print(f"Stored {count} chunks for {args.symbol} ({args.form}).")


if __name__ == "__main__":
    main()
