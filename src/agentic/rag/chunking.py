from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ~4 chars/token rule of thumb: 800 tokens ~= 3200 chars, 100 tokens ~= 400 chars.
_CHUNK_SIZE_CHARS = 3200
_CHUNK_OVERLAP_CHARS = 400


def html_to_text(html: str) -> str:
    """Strip tags/XBRL markup from a filing's primary HTML document."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE_CHARS, chunk_overlap=_CHUNK_OVERLAP_CHARS
    )
    return splitter.split_text(text)
