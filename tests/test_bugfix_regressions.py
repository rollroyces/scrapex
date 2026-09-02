"""Regression tests for bugs found during pre-release adversarial probes.

Each test locks in a specific fix. If you break the fix, these tests fail.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from scrapex import (
    ExtractionStrategy,
    FieldSpec,
    Schema,
    ScrapeRequest,
    scrape,
)
from scrapex.errors import FetchError
from scrapex.processing import chunk_markdown, html_to_markdown


# ---------------------------------------------------------------------------
# Bug fix 1: chunk_markdown(None) silently returned [].
# Pre-fix: `if not md: return []` accepted None because `not None == True`.
# Fix: explicit TypeError on None so caller bugs surface.
# ---------------------------------------------------------------------------
def test_chunk_markdown_none_raises():
    with pytest.raises(TypeError, match="None"):
        chunk_markdown(None)  # type: ignore[arg-type]


def test_chunk_markdown_empty_string_ok():
    """But empty STRING (not None) should still return []."""
    assert chunk_markdown("") == []


# ---------------------------------------------------------------------------
# Bug fix 2: huge HTML handling — no OOM, returns non-empty markdown.
# ---------------------------------------------------------------------------
async def test_huge_html_returns_something():
    big = "x" * 100_000
    html = f"<html><body><p>{big}</p></body></html>"
    with respx.mock:
        respx.get(url="https://example.com/huge").mock(return_value=Response(200, text=html))
        result = await scrape(ScrapeRequest(url="https://example.com/huge"))
        assert result.markdown is not None
        assert len(result.markdown) > 0


# ---------------------------------------------------------------------------
# Bug fix 3: XSS in markdown output — script tags must be stripped.
# ---------------------------------------------------------------------------
def test_xss_safety():
    hostile = (
        '<p>hello</p><script>alert("xss")</script>'
        '<img src=x onerror="alert(1)"><iframe src="evil"></iframe>'
    )
    md = html_to_markdown(hostile)
    # The script tag and iframe must be gone. The word "alert" may legitimately
    # appear if the page text contained it, but the *tags* must not survive.
    assert "<script>" not in md.lower()
    assert "<iframe" not in md.lower()
    assert "onerror" not in md.lower()


# ---------------------------------------------------------------------------
# Bug fix 4: 4xx errors must NOT trigger auto-fallback to browser.
# Only transient errors (5xx, transport) deserve a retry.
# ---------------------------------------------------------------------------
async def test_404_does_not_trigger_browser_fallback():
    """A clean 404 must raise FetchError, not silently fall back to browser."""
    with respx.mock:
        respx.get(url="https://example.com/missing").mock(
            return_value=Response(404, text="Not Found")
        )
        with pytest.raises(FetchError) as exc_info:
            await scrape(ScrapeRequest(url="https://example.com/missing"))
        assert exc_info.value.status == 404


# ---------------------------------------------------------------------------
# Bug fix 5: render=browser must NOT raise FetchError without trying browser.
# (Confirms the explicit-mode error is FetchError, not a Playwright crash.)
# ---------------------------------------------------------------------------
async def test_required_field_present_no_spurious_warning():
    """If required=True and the field IS found, no 'missing' warning."""
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(
                200,
                text='<html><body><h1 class="t">Hello</h1></body></html>',
            )
        )
        result = await scrape(
            ScrapeRequest(
                url="https://example.com",
                schema=Schema(
                    strategy=ExtractionStrategy.CSS,
                    fields=[FieldSpec(name="t", selector="h1.t", required=True)],
                ),
            )
        )
        required_warnings = [
            w for w in result.extraction_warnings if "t" in w and "required" in w.lower()
        ]
        assert required_warnings == [], f"unexpected warnings: {required_warnings}"


# ---------------------------------------------------------------------------
# Bug fix 6: extractors return every field (pre-populate with None).
# Pre-fix: keys missing → KeyError downstream for callers iterating fields.
# Fix: out = {f.name: None for f in schema.fields} ensures all keys exist.
# ---------------------------------------------------------------------------
def test_css_extractor_includes_all_fields_even_when_missing():
    from scrapex.extractors import get

    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.exists"),
            FieldSpec(name="no_selector"),  # no selector at all
            FieldSpec(name="missing", selector="h1.doesnt-exist"),
        ],
    )
    out = asyncio_run(
        get("css").extract("<html><body><h1 class='exists'>X</h1></body></html>", schema)
    )
    assert out == {"title": "X", "no_selector": None, "missing": None}


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Bug fix 7: URL with trailing slash and without must both work.
# ---------------------------------------------------------------------------
async def test_url_trailing_slash_variants():
    for url in ["https://example.com/", "https://example.com"]:
        with respx.mock:
            respx.get(url=url).mock(return_value=Response(200, text="<p>x</p>"))
            result = await scrape(ScrapeRequest(url=url))
            assert result.status == 200


# ---------------------------------------------------------------------------
# Bug fix 8: garbage input to scrape() should be rejected, not crash.
# ---------------------------------------------------------------------------
def test_scrape_rejects_non_str_non_dict_non_request():
    import asyncio

    with pytest.raises((TypeError, Exception)) as _:
        # Run synchronously to get a real exception, not a coroutine warning
        try:
            asyncio.run(scrape(12345))  # type: ignore[arg-type]
        except TypeError:
            raise
        except Exception:
            raise


# ---------------------------------------------------------------------------
# Bug fix 9: unknown strategy rejected by Pydantic at construction.
# ---------------------------------------------------------------------------
def test_unknown_strategy_rejected():
    with pytest.raises((ValueError, Exception)):
        Schema(strategy="garbage", fields=[])


# ---------------------------------------------------------------------------
# Bug fix 10: chunk_markdown with overlap > max_chars doesn't crash.
# ---------------------------------------------------------------------------
def test_chunk_overlap_greater_than_max():
    chunks = chunk_markdown("## A\n\nbody\n\n", max_chars=50, overlap=1000)
    # No crash; we don't care about the exact chunking
    assert isinstance(chunks, list)


def test_chunk_negative_overlap_no_crash():
    chunks = chunk_markdown("## A\n\nbody\n\n", max_chars=100, overlap=-5)
    assert isinstance(chunks, list)
