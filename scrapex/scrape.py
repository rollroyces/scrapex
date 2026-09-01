"""The main ``scrape()`` orchestrator — the only public entry point.

This file owns the request lifecycle:
    1. Pick a fetcher (HTTP, browser, or auto).
    2. Fetch the page (with retries on transient failures).
    3. Convert HTML → markdown.
    4. Run the chosen extraction strategy.
    5. Bundle everything into :class:`ScrapeResult`.

The orchestrator never imports strategy implementations; it goes through
the registry so new strategies can register themselves without changes here.
"""
from __future__ import annotations

import re
import time
from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from scrapex.errors import FetchError, RenderError
from scrapex.extractors import get as get_extractor
from scrapex.extractors.llm import get_llm_extractor
from scrapex.fetchers import FetchedPage, Fetcher, choose_fetcher
from scrapex.models import (
    ExtractionStrategy,
    RenderMode,
    ScrapeRequest,
    ScrapeResult,
)
from scrapex.processing import html_to_markdown

# Heuristic markers that strongly suggest "you need JS to render this"
_JS_MARKERS = re.compile(
    r"<script[^>]*src=|<div[^>]+id=\"root\"|window\.__NEXT_DATA__|"
    r"<noscript>|enable\s+javascript|please enable js",
    re.IGNORECASE,
)


def _page_likely_needs_js(html: str) -> bool:
    """Cheap heuristic: do we see common JS-only markers?"""
    if len(html) < 500:
        return True
    return bool(_JS_MARKERS.search(html))


async def _fetch_with_retry(
    fetcher: Fetcher, request: ScrapeRequest, *, render_mode: str
) -> FetchedPage:
    """Fetch with tenacity retries on transient errors only.

    Retries are only triggered on network/transport failures. A clean HTTP
    404 (or other 4xx) is treated as definitive — the server told us the
    page is gone, no point trying again.
    """
    retryer = AsyncRetrying(
        stop=stop_after_attempt(request.max_retries + 1),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_is_transient),
        reraise=True,
    )
    async for attempt in retryer:
        with attempt:
            result: FetchedPage = await fetcher.fetch(
                str(request.url),
                timeout_s=request.timeout_s,
                user_agent=request.user_agent,
                proxy=request.proxy,
            )
            return result
    raise FetchError(str(request.url), "exhausted retries")  # pragma: no cover


def _is_transient(exc: BaseException) -> bool:
    """Only retry / auto-fallback on transport errors and 5xx; not on 4xx."""
    if isinstance(exc, RenderError):
        # Playwright crashed — not transient, no point retrying
        return False
    if isinstance(exc, FetchError):
        # 4xx = client error, definitive; 5xx = server error, worth retrying
        if exc.status is None:
            return True  # transport-level
        return exc.status >= 500
    return False


async def scrape(request: ScrapeRequest | dict[str, Any] | str) -> ScrapeResult:
    """Fetch + clean + extract in one call.

    Examples
    --------
    >>> import asyncio
    >>> from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy
    >>> req = ScrapeRequest(
    ...     url="https://example.com",
    ...     schema=Schema(
    ...         strategy=ExtractionStrategy.CSS,
    ...         fields=[FieldSpec(name="title", selector="h1")],
    ...     ),
    ... )
    >>> result = asyncio.run(scrape(req))
    >>> result.extracted
    {'title': 'Example Domain'}
    """
    # Accept dict / str for ergonomics — normalise to ScrapeRequest
    if isinstance(request, str):
        req = ScrapeRequest(url=request)  # type: ignore[arg-type]
    elif isinstance(request, dict):
        req = ScrapeRequest(**request)
    elif isinstance(request, ScrapeRequest):
        req = request
    else:
        raise TypeError(f"scrape() accepts ScrapeRequest, dict, or str; got {type(request)}")

    t0 = time.monotonic()
    warnings: list[str] = []

    # Decide fetcher mode
    mode_value = req.render.value if isinstance(req.render, RenderMode) else str(req.render)
    primary_mode = "http" if mode_value == "auto" else mode_value

    fetcher = await choose_fetcher(primary_mode, proxy=req.proxy)
    try:
        page = await _fetch_with_retry(fetcher, req, render_mode=primary_mode)
    except FetchError as first_err:
        # Only auto-fallback to browser when the failure looks transient
        # (transport error or 5xx). 4xx means the page really isn't there.
        if mode_value == "auto" and _is_transient(first_err):
            warnings.append("HTTP fetch failed; falling back to browser rendering")
            await fetcher.aclose()
            bf = await choose_fetcher("browser", proxy=req.proxy)
            try:
                page = await _fetch_with_retry(bf, req, render_mode="browser")
                fetcher = bf
            except (FetchError, RenderError):
                await bf.aclose()
                raise
        else:
            raise

    # Convert to markdown
    md: str | None = None
    if req.include_markdown:
        md = html_to_markdown(page.html, max_chars=req.markdown_max_chars)

    # Extract
    extracted: dict[str, Any] = {}
    if req.schema_ is not None:
        strat = req.schema_.strategy
        if strat == ExtractionStrategy.NONE:
            extracted = {}
        elif strat == ExtractionStrategy.LLM:
            # Auto-resolve China preset names (e.g. "deepseek-v3") to the
            # full litellm model string + region-aware api_base + env key.
            llm_model = req.llm_model
            llm_api_key = req.llm_api_key
            api_base: str | None = None
            try:
                from scrapex.china_llm import get as get_preset
                from scrapex.china_llm import resolve as resolve_preset

                preset = get_preset(llm_model) if llm_model else None
                if preset is not None and llm_model is not None:
                    resolved = resolve_preset(
                        llm_model, region=req.llm_region, api_key=llm_api_key
                    )
                    llm_model = resolved["model"]
                    llm_api_key = resolved.get("api_key", llm_api_key)
                    api_base = resolved.get("api_base")
            except KeyError:
                # Not a preset name — treat as raw litellm model string.
                pass
            extracted = await get_llm_extractor().extract(
                page.html,
                req.schema_,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                api_base=api_base,
                markdown=md,
            )
        else:
            extractor = get_extractor(strat.value)
            extracted = await extractor.extract(page.html, req.schema_)
        # Build warnings for missing required fields
        for f in req.schema_.fields:
            if f.required and not extracted.get(f.name):
                warnings.append(f"required field '{f.name}' was not found")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ScrapeResult(
        url=str(req.url),
        final_url=page.url,
        status=page.status,
        title=page.title or _title_from_md(md),
        markdown=md,
        html=page.html if not req.include_markdown else None,
        extracted=extracted,
        extraction_warnings=warnings,
        render_mode_used=page.render_mode,
        elapsed_ms=elapsed_ms,
    )


def _title_from_md(md: str | None) -> str | None:
    """Fallback title extraction from markdown's first heading."""
    if not md:
        return None
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


__all__ = ["scrape"]
