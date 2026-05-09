"""
Parallel PDF ingestion — all documents processed concurrently.
Target: 30s from upload to structured text.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.ingestion.pdf_reader import PageText, extract_pages, full_text

_executor = ThreadPoolExecutor(max_workers=8)


def _process_one(source: str | Path | bytes) -> dict:
    """Synchronous extraction for one PDF — runs in a thread."""
    pages = extract_pages(source)
    return {
        "pages": pages,
        "full_text": full_text(pages),
        "page_count": len(pages),
        "has_ocr": any(p.is_ocr for p in pages),
    }


async def process_pdfs_async(sources: list[str | Path | bytes]) -> list[dict]:
    """
    Process multiple PDFs in parallel.
    Each result dict has: pages, full_text, page_count, has_ocr.
    """
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(_executor, _process_one, src) for src in sources]
    return await asyncio.gather(*tasks)


def process_pdfs(sources: list[str | Path | bytes]) -> list[dict]:
    """Synchronous wrapper — use when not already in an async context."""
    return asyncio.run(process_pdfs_async(sources))
