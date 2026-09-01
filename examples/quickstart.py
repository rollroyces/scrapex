"""Quick example — run with ``python examples/quickstart.py``.

Make sure ``OPENAI_API_KEY`` is set in your environment first.
"""
from __future__ import annotations

import asyncio

from scrapex import (
    ExtractionStrategy,
    FieldSpec,
    Schema,
    ScrapeRequest,
    scrape,
)


async def main() -> None:
    # 1. Simplest possible call — just get the markdown
    print("=== Markdown-only ===")
    result = await scrape("https://example.com")
    print(f"Title: {result.title}")
    print(f"Markdown (first 200 chars):\n{result.markdown[:200]}...\n")

    # 2. CSS extraction
    print("=== CSS extraction ===")
    result = await scrape(
        ScrapeRequest(
            url="https://example.com",
            schema=Schema(
                strategy=ExtractionStrategy.CSS,
                fields=[
                    FieldSpec(name="title", selector="h1"),
                    FieldSpec(name="paragraph", selector="p"),
                ],
            ),
        )
    )
    print(f"Extracted: {result.extracted}\n")

    # 3. LLM extraction (requires OPENAI_API_KEY)
    print("=== LLM extraction (requires API key) ===")
    result = await scrape(
        ScrapeRequest(
            url="https://example.com",
            schema=Schema(
                strategy=ExtractionStrategy.LLM,
                fields=[
                    FieldSpec(name="domain", description="The domain name on the page"),
                    FieldSpec(name="purpose", description="The stated purpose of the page"),
                ],
            ),
            llm_model="gpt-4o-mini",
        )
    )
    print(f"Extracted: {result.extracted}")
    print(f"Warnings: {result.extraction_warnings}")


if __name__ == "__main__":
    asyncio.run(main())
