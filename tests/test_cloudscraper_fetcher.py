"""Tests for CloudscraperFetcher — async wrapper around cloudscraper.

cloudscraper is sync (requests-based); we run each fetch in a thread
executor. These tests mock cloudscraper to verify the wrapper's
contract: thread dispatch, error mapping, status propagation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scrapex.errors import FetchError, RenderError


class _FakeResponse:
    """Minimal stand-in for cloudscraper's response object."""

    def __init__(self, status: int, url: str, text: str) -> None:
        self.status_code = status
        self.url = url
        self.text = text


@pytest.fixture
def mock_cs_module():
    """Patch the cloudscraper module reference used by the fetcher."""
    with patch.dict("sys.modules", {"cloudscraper": MagicMock()}):
        yield


@pytest.fixture
def fetcher(mock_cs_module):
    """Build a CloudscraperFetcher with cloudscraper mocked."""
    import scrapex.fetchers.cloudscraper_fetcher as cf

    mock_scraper = MagicMock()
    mock_cs = MagicMock()
    mock_cs.create_scraper.return_value = mock_scraper
    # Patch the module reference the fetcher uses. We patch
    # sys.modules so the lazy import inside the fetcher also sees it.
    with patch.dict("sys.modules", {"cloudscraper": mock_cs}):
        f = cf.CloudscraperFetcher()
        f._scraper = mock_scraper
        yield f


# --- Constructor behavior -----------------------------------------------


def test_cloudscraper_fetcher_raises_when_dep_missing():
    """If cloudscraper is not installed, raise RenderError on construction."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cloudscraper":
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        pytest.raises(RenderError, match="stealth"),
    ):
        from scrapex.fetchers.cloudscraper_fetcher import CloudscraperFetcher

        CloudscraperFetcher()


def test_cloudscraper_fetcher_creates_scraper_with_interpreter():
    """cloudscraper.create_scraper() is called with the interpreter arg."""
    import sys

    mock_cs = MagicMock()
    # Patch sys.modules['cloudscraper'] so both imports inside the
    # fetcher module see the same mock.
    with patch.dict(sys.modules, {"cloudscraper": mock_cs}):
        from scrapex.fetchers.cloudscraper_fetcher import CloudscraperFetcher

        f = CloudscraperFetcher(interpreter="nodejs")
    assert mock_cs.create_scraper.called
    kwargs = mock_cs.create_scraper.call_args.kwargs
    assert kwargs["interpreter"] == "nodejs"
    assert f._interpreter == "nodejs"


# --- Fetch behavior ------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_page_on_2xx(fetcher):
    """200 response becomes a FetchedPage with the right fields."""
    fetcher._scraper.get.return_value = _FakeResponse(
        status=200,
        url="https://example.com/",
        text="<html><title>Example</title><body>hi</body></html>",
    )
    page = await fetcher.fetch(
        "https://example.com/",
        timeout_s=10.0,
        user_agent=None,
        proxy=None,
    )
    assert page.status == 200
    assert page.url == "https://example.com/"
    assert page.render_mode == "http"
    assert page.title == "Example"
    assert "hi" in page.html


@pytest.mark.asyncio
async def test_fetch_raises_fetcherror_on_4xx(fetcher):
    """403 response becomes a FetchError, not a cloudscraper exception."""
    fetcher._scraper.get.return_value = _FakeResponse(
        status=403, url="https://example.com/", text=""
    )
    with pytest.raises(FetchError) as ei:
        await fetcher.fetch(
            "https://example.com/", timeout_s=10.0, user_agent=None, proxy=None
        )
    assert ei.value.status == 403
    assert "cloudscraper" in str(ei.value)


@pytest.mark.asyncio
async def test_fetch_raises_fetcherror_on_5xx(fetcher):
    """500 response also becomes a FetchError."""
    fetcher._scraper.get.return_value = _FakeResponse(
        status=500, url="https://example.com/", text=""
    )
    with pytest.raises(FetchError) as ei:
        await fetcher.fetch(
            "https://example.com/", timeout_s=10.0, user_agent=None, proxy=None
        )
    assert ei.value.status == 500


@pytest.mark.asyncio
async def test_fetch_wraps_cloudscraper_exception(fetcher):
    """If cloudscraper raises (network, etc), wrap in FetchError."""
    import requests

    fetcher._scraper.get.side_effect = requests.exceptions.ConnectionError("net down")
    with pytest.raises(FetchError, match="cloudscraper failed"):
        await fetcher.fetch(
            "https://example.com/", timeout_s=10.0, user_agent=None, proxy=None
        )


@pytest.mark.asyncio
async def test_fetch_passes_timeout_to_cloudscraper(fetcher):
    """timeout_s from the caller is forwarded to cloudscraper."""
    fetcher._scraper.get.return_value = _FakeResponse(200, "https://x/", "<html/>")
    await fetcher.fetch(
        "https://example.com/", timeout_s=42.0, user_agent=None, proxy=None
    )
    kwargs = fetcher._scraper.get.call_args.kwargs
    assert kwargs["timeout"] == 42.0


@pytest.mark.asyncio
async def test_fetch_passes_user_agent_when_provided(fetcher):
    """user_agent override is sent as User-Agent header."""
    fetcher._scraper.get.return_value = _FakeResponse(200, "https://x/", "<html/>")
    await fetcher.fetch(
        "https://example.com/",
        timeout_s=10.0,
        user_agent="MyUA/1.0",
        proxy=None,
    )
    headers = fetcher._scraper.get.call_args.kwargs.get("headers", {})
    assert headers.get("User-Agent") == "MyUA/1.0"


@pytest.mark.asyncio
async def test_fetch_omits_user_agent_when_not_provided(fetcher):
    """No user_agent → no headers dict (let cloudscraper pick)."""
    fetcher._scraper.get.return_value = _FakeResponse(200, "https://x/", "<html/>")
    await fetcher.fetch(
        "https://example.com/", timeout_s=10.0, user_agent=None, proxy=None
    )
    kwargs = fetcher._scraper.get.call_args.kwargs
    # 'headers' should not be passed at all when user_agent is None
    assert "headers" not in kwargs


# --- choose_fetcher integration -----------------------------------------


@pytest.mark.asyncio
async def test_choose_fetcher_with_stealth_returns_cloudscraper():
    """stealth=True returns a CloudscraperFetcher, not HttpFetcher."""
    from scrapex.fetchers import choose_fetcher
    from scrapex.fetchers.cloudscraper_fetcher import CloudscraperFetcher

    mock_cs = MagicMock()
    with patch.dict("sys.modules", {"cloudscraper": mock_cs}):
        f = await choose_fetcher("http", stealth=True)
    assert isinstance(f, CloudscraperFetcher)
    await f.aclose()


@pytest.mark.asyncio
async def test_choose_fetcher_without_stealth_returns_http():
    """stealth=False (default) returns the plain HttpFetcher."""
    from scrapex.fetchers import HttpFetcher, choose_fetcher

    f = await choose_fetcher("http", stealth=False)
    assert isinstance(f, HttpFetcher)
    await f.aclose()


@pytest.mark.asyncio
async def test_choose_fetcher_browser_ignores_stealth():
    """Browser mode is unaffected by stealth flag."""
    from scrapex.fetchers import BrowserFetcher, choose_fetcher

    f = await choose_fetcher("browser", stealth=True)
    assert isinstance(f, BrowserFetcher)
    await f.aclose()


# --- Lifecycle ----------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_calls_session_close(fetcher):
    """aclose() closes the underlying cloudscraper session."""
    fetcher._scraper.close = MagicMock()
    await fetcher.aclose()
    fetcher._scraper.close.assert_called_once()


@pytest.mark.asyncio
async def test_aclose_handles_missing_close_method(fetcher):
    """If cloudscraper version lacks .close(), aclose() is a no-op."""
    # Replace close with a sentinel that's not callable
    if hasattr(fetcher._scraper, "close"):
        del fetcher._scraper.close
    # Should not raise
    await fetcher.aclose()


# --- Reuse (multiple fetches per CloudscraperFetcher) --------------------


@pytest.mark.asyncio
async def test_fetcher_can_be_reused_across_calls(fetcher):
    """Same fetcher instance should handle multiple URLs without state leaks."""
    fetcher._scraper.get.side_effect = [
        _FakeResponse(200, "https://a/", "<html><title>A</title></html>"),
        _FakeResponse(200, "https://b/", "<html><title>B</title></html>"),
    ]
    p1 = await fetcher.fetch(
        "https://a/", timeout_s=10.0, user_agent=None, proxy=None
    )
    p2 = await fetcher.fetch(
        "https://b/", timeout_s=10.0, user_agent=None, proxy=None
    )
    assert p1.title == "A"
    assert p2.title == "B"
    assert fetcher._scraper.get.call_count == 2
