"""Spike 003c — does a fluent DSL beat raw Playwright on line count?

Two implementations of the same workflow, side by side. Measure:
- Lines of user code
- Readability (subjective — count "naming" verbosity)
- Whether scrapex's existing Schema system can be reused for the
  extraction step
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from scrapex import Schema, FieldSpec, ExtractionStrategy

# Same mock server as 003b. Reusing to keep this probe short.
from importlib import import_module
import sys

# --- The probe ---


async def with_raw_playwright(base_url: str) -> dict:
    """13 lines. Baseline. (See probe.py in 003b.)"""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page: Page = await ctx.new_page()
            await page.goto(f"{base_url}/login")
            await page.fill("#u", "alice")
            await page.fill("#p", "secret")
            await page.click("#go")
            await page.wait_for_url("**/dashboard")
            pdf_href = await page.get_attribute("#pdf", "href")
            title = await page.text_content("h1")
            return {"pdf_href": pdf_href, "title": title}
        finally:
            await browser.close()


class BrowserSession:
    """Hypothetical thin DSL: a fluent chain over Playwright.

    The selling point vs raw Playwright: reuses scrapex's Schema system
    for the final extraction, so the user gets extraction AND browser
    automation in one object.
    """

    def __init__(self, browser: Browser):
        self._browser = browser
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._page:
            await self._page.close()
        if self._ctx:
            await self._ctx.close()
        await self._browser.close()

    async def new_page(self) -> "BrowserSession":
        self._ctx = await self._browser.new_context()
        self._page = await self._ctx.new_page()
        return self

    async def goto(self, url: str) -> "BrowserSession":
        assert self._page is not None
        await self._page.goto(url)
        return self

    async def fill(self, selector: str, value: str) -> "BrowserSession":
        assert self._page is not None
        await self._page.fill(selector, value)
        return self

    async def click(self, selector: str) -> "BrowserSession":
        assert self._page is not None
        await self._page.click(selector)
        return self

    async def wait_for_url(self, pattern: str) -> "BrowserSession":
        assert self._page is not None
        await self._page.wait_for_url(pattern)
        return self

    async def extract(self, schema: Schema) -> dict:
        """Apply scrapex's HTML extraction to the current page."""
        assert self._page is not None
        html = await self._page.content()
        # The real scrapex would route this through the orchestrator,
        # but for the spike we just call the CSS extractor directly.
        from scrapex.extractors import get
        return await get("css").extract(html, schema)


async def with_dsl(base_url: str) -> dict:
    """Use BrowserSession. Same workflow, count the lines."""
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1"),
            FieldSpec(name="pdf_href", selector="#pdf", attr="href"),
        ],
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        async with BrowserSession(browser) as session:
            await session.new_page()
            await session.goto(f"{base_url}/login")
            await session.fill("#u", "alice")
            await session.fill("#p", "secret")
            await session.click("#go")
            await session.wait_for_url("**/dashboard")
            return await session.extract(schema)


async def main() -> None:
    # Reuse the server from 003b
    sys.path.insert(0, "../003b-headless-browser")
    mod = import_module("probe")
    runner, port = await mod.start_server()
    base = f"http://127.0.0.1:{port}"
    try:
        # Raw Playwright
        raw_result = await with_raw_playwright(base)
        print(f"RAW:    {raw_result}")

        # DSL
        dsl_result = await with_dsl(base)
        print(f"DSL:    {dsl_result}")

        # Compare
        if raw_result["pdf_href"] == dsl_result["pdf_href"]:
            print("✓ Both extract the same pdf_href")
        else:
            print(f"✗ MISMATCH: raw={raw_result['pdf_href']!r} dsl={dsl_result['pdf_href']!r}")

        # Line counts
        import inspect
        raw_src = inspect.getsource(with_raw_playwright)
        dsl_src = inspect.getsource(with_dsl)

        def count_actionable(src: str) -> int:
            # Count non-blank, non-comment, non-async-def, non-decorator lines
            lines = 0
            for line in src.splitlines():
                s = line.strip()
                if not s or s.startswith(("#", "async def", "def ", "@", '"""', "'''")):
                    continue
                # Skip type-annotation lines and docstrings
                if ":" in s and "(" not in s and "=" not in s:
                    continue
                lines += 1
            return lines

        print(f"\nRaw Playwright: {count_actionable(raw_src)} actionable lines")
        print(f"With DSL:       {count_actionable(dsl_src)} actionable lines")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())