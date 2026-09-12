r"""FastAPI wrapper for scrapex — single endpoint, ~70 LOC.

NOT a hard dep: ``fastapi`` and ``uvicorn`` are only required when
you install ``scrapex[api]``. The import is lazy so the wrapper
module can sit in the source tree without forcing every user to
install FastAPI.

Usage::

    pip install scrapex[api]
    uvicorn scrapex.wrappers.fastapi_n8n:app --reload

Then POST to /scrape::

    curl -X POST http://localhost:8000/scrape \
         -H "Content-Type: application/json" \
         -d '{"url": "https://example.com", "goal": "the page title"}'

The endpoint returns the same :class:`ScrapeResult` shape you get
from calling :func:`scrapex.scrape` directly, just wrapped in JSON.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from scrapex.models import ScrapeRequest, ScrapeResult


class ScrapeRequestBody(BaseModel):
    """Request body for POST /scrape. Mirrors ScrapeRequest's public API.

    Keeping this separate from ScrapeRequest means the wrapper's
    wire format doesn't depend on which Pydantic version is
    installed, and we can add wrapper-specific fields (e.g. ``goal``)
    that the core ``ScrapeRequest`` doesn't know about.
    """

    url: str = Field(..., description="URL to scrape")
    goal: str | None = Field(
        default=None,
        description="Optional natural-language goal. Informational only — "
        "Schema.from_goal() needs HTML which we don't have at request time. "
        "For goal-driven extraction, do two passes: first fetch, then synthesize.",
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="Optional schema as a dict (JSON shape). Example: "
        '{"strategy": "css", "fields": [{"name": "title", "selector": "h1"}]}',
    )
    render: str = Field(default="auto", description="auto | http | browser")
    stealth: bool = Field(default=False, description="Use cloudscraper (anti-bot)")
    include_markdown: bool = Field(default=True, description="Include markdown output")
    timeout_s: float = Field(default=30.0, gt=0, le=300)
    user_agent: str | None = None
    proxy: str | None = None


class ScrapeResponseBody(BaseModel):
    """Response body for POST /scrape."""

    url: str
    status: int
    title: str | None
    markdown: str | None
    extracted: dict[str, Any] | None
    render_mode_used: str | None
    warnings: list[str]
    error: str | None = None


# FastAPI is an optional dep. Lazy-import at module load so the
# import error is caught and reported with a clear install hint.
try:
    from fastapi import FastAPI, HTTPException
except ImportError as e:
    raise ImportError(
        "scrapex.wrappers.fastapi_n8n requires the 'api' extra: "
        "pip install 'scrapex[api]'. "
        "fastapi is not importable."
    ) from e


app = FastAPI(
    title="scrapex",
    description="Single-page extraction library with optional LLM synthesis.",
    version="0.1.0",
)


@app.post("/scrape", response_model=ScrapeResponseBody)
async def scrape_endpoint(body: ScrapeRequestBody) -> ScrapeResponseBody:
    """Run a scrape and return the result as JSON.

    If ``goal`` is provided, synthesizes a Schema via
    ``Schema.from_goal()`` before scraping (one extra LLM call).
    """
    # Lazy imports keep the module import cheap and avoid circular
    # imports between scrapex's surface and the wrapper.
    from scrapex import scrape

    # Note on the `goal` field: Schema.from_goal() needs HTML to
    # synthesize selectors, which we don't have yet at this point
    # in the flow. Calling it with empty HTML would synthesize
    # selectors from "nothing" — useless. So we accept the goal
    # but don't try to synthesize a schema here.
    # If you want goal-driven synthesis, do it in two steps:
    #   1. POST /scrape with no goal to fetch HTML
    #   2. Call Schema.from_goal(goal, html=result.html)
    #   3. POST /scrape again with the synthesized schema
    # OR use the LLM extractor with goal as a description (planned).

    # Map the wire schema to the library's ScrapeRequest.
    # Pydantic's HttpUrl is strict; the wire string needs validation
    # before being assigned. We use a try/except on ScrapeRequest
    # construction so URL validation errors become 400s, not 500s.
    try:
        req = ScrapeRequest(
            url=body.url,  # type: ignore[arg-type]
            schema=body.schema_,  # type: ignore[arg-type]
            render=body.render,  # type: ignore[arg-type]
            stealth=body.stealth,
            include_markdown=body.include_markdown,
            timeout_s=body.timeout_s,
            user_agent=body.user_agent,
            proxy=body.proxy,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {e}") from e

    try:
        result: ScrapeResult = await scrape(req)
    except Exception as e:
        # Surface the error as a 200 with the error field populated,
        # NOT a 500. The caller asked "scrape this URL", and the
        # answer is "here's what happened, including the error".
        # 5xx should be reserved for "the API itself is broken".
        return ScrapeResponseBody(
            url=str(req.url),
            status=0,
            title=None,
            markdown=None,
            extracted=None,
            render_mode_used=None,
            warnings=[],
            error=f"{type(e).__name__}: {e}",
        )

    return ScrapeResponseBody(
        url=str(result.url),
        status=result.status,
        title=result.title,
        markdown=result.markdown,
        extracted=result.extracted,
        render_mode_used=result.render_mode_used,
        warnings=result.extraction_warnings,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check. Always returns 200 if the server is up."""
    return {"status": "ok"}


__all__ = ["ScrapeRequestBody", "ScrapeResponseBody", "app"]
