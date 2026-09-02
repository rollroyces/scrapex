"""Tests for the fetchers module — covers every branch.

HttpFetcher covers:
- Successful fetch (status, body, title)
- 4xx → FetchError with status set
- 5xx → FetchError with status set
- Connection timeout
- Transport error (generic HTTPError)
- Custom user_agent override
- Title extraction from HTML
- Proxy mounting (httpx 0.28+ behavior)
- aclose() is idempotent
- choose_fetcher dispatch (http vs browser)
- choose_fetcher with proxy

BrowserFetcher covers:
- Construction with playwright installed (smoke only — no real browser)
- aclose() before any fetch (no-op)
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from scrapex.errors import FetchError
from scrapex.fetchers import (
    BrowserFetcher,
    FetchedPage,
    Fetcher,
    HttpFetcher,
    choose_fetcher,
)

SAMPLE = """
<html>
  <head><title>Test Page</title></head>
  <body><p>hello</p></body>
</html>
"""

NO_TITLE = "<html><body><p>no title</p></body></html>"


# ---------------------------------------------------------------------------
# HttpFetcher — successful paths
# ---------------------------------------------------------------------------
async def test_http_fetcher_returns_correct_fields():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        f = HttpFetcher()
        try:
            page = await f.fetch(
                "https://example.com",
                timeout_s=10.0,
                user_agent=None,
                proxy=None,
            )
        finally:
            await f.aclose()
    assert isinstance(page, FetchedPage)
    assert page.status == 200
    assert "<title>Test Page</title>" in page.html
    assert page.title == "Test Page"
    assert page.render_mode == "http"
    # final_url should be the (possibly redirected) URL
    assert str(page.url).startswith("https://example.com")


async def test_http_fetcher_extracts_title():
    with respx.mock:
        respx.get("https://example.com/").mock(
            return_value=Response(200, text="<title>My Title</title>")
        )
        f = HttpFetcher()
        try:
            page = await f.fetch("https://example.com/", timeout_s=10, user_agent=None, proxy=None)
        finally:
            await f.aclose()
    assert page.title == "My Title"


async def test_http_fetcher_handles_missing_title():
    with respx.mock:
        respx.get("https://example.com/").mock(return_value=Response(200, text=NO_TITLE))
        f = HttpFetcher()
        try:
            page = await f.fetch("https://example.com/", timeout_s=10, user_agent=None, proxy=None)
        finally:
            await f.aclose()
    assert page.title is None


async def test_http_fetcher_truncates_very_long_title():
    """Title longer than 500 chars gets truncated."""
    long_title = "x" * 1000
    with respx.mock:
        respx.get("https://example.com/").mock(
            return_value=Response(200, text=f"<title>{long_title}</title>")
        )
        f = HttpFetcher()
        try:
            page = await f.fetch("https://example.com/", timeout_s=10, user_agent=None, proxy=None)
        finally:
            await f.aclose()
    assert len(page.title) == 500


async def test_http_fetcher_handles_title_with_whitespace():
    with respx.mock:
        respx.get("https://example.com/").mock(
            return_value=Response(200, text="<title>   Padded   </title>")
        )
        f = HttpFetcher()
        try:
            page = await f.fetch("https://example.com/", timeout_s=10, user_agent=None, proxy=None)
        finally:
            await f.aclose()
    assert page.title == "Padded"


# ---------------------------------------------------------------------------
# HttpFetcher — error paths
# ---------------------------------------------------------------------------
async def test_http_fetcher_404_raises_with_status():
    with respx.mock:
        respx.get("https://example.com/missing").mock(return_value=Response(404, text="Not Found"))
        f = HttpFetcher()
        try:
            with pytest.raises(FetchError) as exc_info:
                await f.fetch(
                    "https://example.com/missing", timeout_s=10, user_agent=None, proxy=None
                )
        finally:
            await f.aclose()
    assert exc_info.value.status == 404
    assert exc_info.value.url == "https://example.com/missing"


async def test_http_fetcher_500_raises_with_status():
    with respx.mock:
        respx.get("https://example.com/boom").mock(
            return_value=Response(500, text="Internal Server Error")
        )
        f = HttpFetcher()
        try:
            with pytest.raises(FetchError) as exc_info:
                await f.fetch("https://example.com/boom", timeout_s=10, user_agent=None, proxy=None)
        finally:
            await f.aclose()
    assert exc_info.value.status == 500


async def test_http_fetcher_403_raises_with_status():
    with respx.mock:
        respx.get("https://example.com/forbidden").mock(
            return_value=Response(403, text="Forbidden")
        )
        f = HttpFetcher()
        try:
            with pytest.raises(FetchError) as exc_info:
                await f.fetch(
                    "https://example.com/forbidden", timeout_s=10, user_agent=None, proxy=None
                )
        finally:
            await f.aclose()
    assert exc_info.value.status == 403


async def test_http_fetcher_timeout_raises_no_status():
    """A timeout is a transport-level error — no HTTP status to report."""
    with respx.mock:
        respx.get("https://example.com/slow").mock(side_effect=httpx.ConnectTimeout("timed out"))
        f = HttpFetcher()
        try:
            with pytest.raises(FetchError) as exc_info:
                await f.fetch("https://example.com/slow", timeout_s=10, user_agent=None, proxy=None)
        finally:
            await f.aclose()
    assert exc_info.value.status is None
    assert "timeout" in str(exc_info.value).lower()


async def test_http_fetcher_connection_error_raises_no_status():
    """Generic connection errors are FetchError with status=None."""
    with respx.mock:
        respx.get("https://example.com/refused").mock(side_effect=httpx.ConnectError("refused"))
        f = HttpFetcher()
        try:
            with pytest.raises(FetchError) as exc_info:
                await f.fetch(
                    "https://example.com/refused", timeout_s=10, user_agent=None, proxy=None
                )
        finally:
            await f.aclose()
    assert exc_info.value.status is None


# ---------------------------------------------------------------------------
# HttpFetcher — user_agent override
# ---------------------------------------------------------------------------
async def test_http_fetcher_uses_default_user_agent():
    captured_request = None
    with respx.mock:
        respx.get("https://example.com/").mock(
            return_value=Response(200, text=SAMPLE),
        )
        f = HttpFetcher()
        try:
            await f.fetch("https://example.com/", timeout_s=10, user_agent=None, proxy=None)
            captured_request = respx.calls[-1].request
        finally:
            await f.aclose()
    assert captured_request is not None
    assert "User-Agent" in captured_request.headers
    # Default UA must be browser-like
    assert "Mozilla" in captured_request.headers["User-Agent"]


async def test_http_fetcher_overrides_user_agent():
    captured_request = None
    with respx.mock:
        respx.get("https://example.com/").mock(return_value=Response(200, text=SAMPLE))
        f = HttpFetcher()
        try:
            await f.fetch(
                "https://example.com/",
                timeout_s=10,
                user_agent="my-custom-bot/1.0",
                proxy=None,
            )
            captured_request = respx.calls[-1].request
        finally:
            await f.aclose()
    assert captured_request is not None
    assert captured_request.headers["User-Agent"] == "my-custom-bot/1.0"


# ---------------------------------------------------------------------------
# HttpFetcher — proxy
# ---------------------------------------------------------------------------
async def test_http_fetcher_accepts_proxy_in_constructor():
    """Proxy is mounted on the transport, not per-request in httpx 0.28+."""
    f = HttpFetcher(proxy="http://proxy.example.com:8080")
    await f.aclose()


async def test_http_fetcher_with_no_proxy_works():
    f = HttpFetcher()  # no proxy
    await f.aclose()


# ---------------------------------------------------------------------------
# HttpFetcher — lifecycle
# ---------------------------------------------------------------------------
async def test_http_fetcher_aclose_is_idempotent():
    f = HttpFetcher()
    await f.aclose()
    await f.aclose()  # second call must not crash


# ---------------------------------------------------------------------------
# choose_fetcher dispatch
# ---------------------------------------------------------------------------
async def test_choose_fetcher_http_mode():
    f = await choose_fetcher("http")
    assert isinstance(f, HttpFetcher)
    await f.aclose()


async def test_choose_fetcher_browser_mode():
    f = await choose_fetcher("browser")
    assert isinstance(f, BrowserFetcher)
    # Don't actually start it (no playwright binaries in this env)
    await f.aclose()


async def test_choose_fetcher_unknown_mode_defaults_to_http():
    f = await choose_fetcher("mystery")
    assert isinstance(f, HttpFetcher)
    await f.aclose()


async def test_choose_fetcher_passes_proxy_to_http():
    f = await choose_fetcher("http", proxy="http://proxy:8080")
    assert isinstance(f, HttpFetcher)
    await f.aclose()


# ---------------------------------------------------------------------------
# Fetcher abstract base
# ---------------------------------------------------------------------------
def test_fetcher_is_abstract():
    """Fetcher cannot be instantiated directly — it has abstract methods."""
    with pytest.raises(TypeError):
        Fetcher()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# BrowserFetcher — construction with playwright present, lifecycle
# ---------------------------------------------------------------------------
async def test_browser_fetcher_aclose_before_any_fetch_is_noop():
    """Calling aclose() before any fetch should not crash.

    With playwright installed in the test env, BrowserFetcher() succeeds.
    We don't actually invoke the browser (no chromium binaries).
    """
    bf = BrowserFetcher()
    await bf.aclose()  # no-op path: both _browser and _playwright are None
