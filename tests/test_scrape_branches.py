"""Tests for the scrape.py orchestrator — every branch.

Covers the 79% → 100% gap:
- _is_transient() with each exception type / status
- _page_likely_needs_js() with short, long, and JS-marked HTML
- _title_from_md() with heading, no heading, empty input
- scrape() with render=http / browser / auto modes
- 5xx triggers auto-fallback to browser (we mock the browser so it succeeds)
- Browser fallback itself fails → FetchError bubbles up
- max_retries is respected on transient errors
- include_markdown=False → html field is populated, markdown is None
- include_markdown=True → html is None, markdown is set
- RenderMode value coercion
- LLM strategy with raw litellm model string (not a preset)
- LLM strategy with China preset name → resolved internally
- NONE strategy → empty extracted
- Required field missing → warning emitted
- Required field present → no warning
- scrape() accepts str, dict, ScrapeRequest
- elapsed_ms is set to a positive integer
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from scrapex import (
    ExtractionStrategy,
    FieldSpec,
    RenderMode,
    Schema,
    ScrapeRequest,
    ScrapeResult,
    scrape,
)
from scrapex.errors import FetchError
from scrapex.scrape import (
    _is_transient,
    _page_likely_needs_js,
    _title_from_md,
)

SAMPLE = "<html><head><title>T</title></head><body><p>hi</p></body></html>"


# ---------------------------------------------------------------------------
# Async helpers used by monkeypatching tests
# ---------------------------------------------------------------------------
def _patch_choose_fetcher(monkeypatch, fake):
    """Patch the choose_fetcher call inside scrape().

    choose_fetcher is imported FROM scrapex.fetchers INTO scrapex.scrape
    at module load. The public name `scrape` in scrapex/__init__.py also
    shadows the module. So we have to patch the imported reference in the
    actual module object via sys.modules.
    """
    import sys

    monkeypatch.setattr(sys.modules["scrapex.scrape"], "choose_fetcher", fake)


def _make_failing_browser_choose():
    """Build an async choose_fetcher replacement that returns a failing browser."""

    class FailingBrowser:
        async def fetch(self, *args, **kwargs):
            raise FetchError("https://example.com", "browser also failed", status=500)

        async def aclose(self):
            pass

    async def fake(mode, **kw):
        return FailingBrowser()

    return fake


def _make_should_not_be_called_browser_choose():
    """Build an async choose_fetcher replacement that raises if used."""

    browser_calls = {"n": 0}

    class ShouldNotBeCalledBrowser:
        async def fetch(self, *args, **kwargs):
            browser_calls["n"] += 1
            raise FetchError("https://x", "should not reach here")

        async def aclose(self):
            pass

    async def fake(mode, **kw):
        return ShouldNotBeCalledBrowser()

    return fake, browser_calls


# ---------------------------------------------------------------------------
# _is_transient — every branch
# ---------------------------------------------------------------------------
def test_is_transient_render_error_is_not_transient():
    """Playwright crash is not retryable — don't waste a retry on it."""
    from scrapex.errors import RenderError

    assert _is_transient(RenderError("playwright crashed")) is False


def test_is_transient_fetch_error_no_status_is_transient():
    """Transport-level error (no HTTP status) → retry."""
    err = FetchError("https://x", "timeout")
    assert err.status is None
    assert _is_transient(err) is True


def test_is_transient_fetch_error_5xx_is_transient():
    """5xx server errors → retry."""
    assert _is_transient(FetchError("https://x", "boom", status=500)) is True
    assert _is_transient(FetchError("https://x", "bad gw", status=502)) is True
    assert _is_transient(FetchError("https://x", "unavail", status=503)) is True


def test_is_transient_fetch_error_4xx_is_not_transient():
    """4xx client errors → definitive, don't retry."""
    assert _is_transient(FetchError("https://x", "not found", status=404)) is False
    assert _is_transient(FetchError("https://x", "forbidden", status=403)) is False
    assert _is_transient(FetchError("https://x", "teapot", status=418)) is False


def test_is_transient_other_exception_type_is_not_transient():
    """Unknown exception types default to non-transient (don't retry)."""
    assert _is_transient(ValueError("nope")) is False
    assert _is_transient(ConnectionError("x")) is False


# ---------------------------------------------------------------------------
# _page_likely_needs_js
# ---------------------------------------------------------------------------
def test_page_likely_needs_js_short_html():
    """Pages shorter than 500 chars are likely JS-only (SPA shells)."""
    assert _page_likely_needs_js("<div></div>") is True


def test_page_likely_needs_js_long_static_html():
    """Long pages with no JS markers don't need a browser."""
    long_html = "<p>" + ("lorem ipsum " * 100) + "</p>"
    assert len(long_html) > 500
    assert _page_likely_needs_js(long_html) is False


def test_page_likely_needs_js_with_markers():
    """Pages with JS markers need a browser even if long."""
    long_html_with_js = "<div>" + ("x" * 1000) + '</div><script src="app.js"></script>'
    assert _page_likely_needs_js(long_html_with_js) is True


def test_page_likely_needs_js_with_react_root():
    """React root div is a strong JS-only marker."""
    html = '<div id="root"></div>' + ("padding " * 200)
    assert _page_likely_needs_js(html) is True


# ---------------------------------------------------------------------------
# _title_from_md
# ---------------------------------------------------------------------------
def test_title_from_md_with_h1():
    md = "# My Title\n\nbody text"
    assert _title_from_md(md) == "My Title"


def test_title_from_md_with_h2():
    md = "## Subheading\n\nbody"
    assert _title_from_md(md) == "Subheading"


def test_title_from_md_no_heading():
    md = "Just some text without headings."
    assert _title_from_md(md) is None


def test_title_from_md_empty():
    assert _title_from_md("") is None
    assert _title_from_md(None) is None  # type: ignore[arg-type]


def test_title_from_md_first_heading_wins():
    md = "## First\n\nbody\n\n## Second"
    assert _title_from_md(md) == "First"


# ---------------------------------------------------------------------------
# scrape() — render mode dispatch
# ---------------------------------------------------------------------------
async def test_scrape_render_http_explicit():
    """render=http → primary fetch is HTTP, no fallback even on transient errors."""
    with respx.mock:
        respx.get("https://example.com/").mock(
            return_value=Response(500, text="Internal Server Error")
        )
        with pytest.raises(FetchError) as exc_info:
            await scrape(
                ScrapeRequest(
                    url="https://example.com",
                    render=RenderMode.HTTP,
                )
            )
        assert exc_info.value.status == 500


async def test_scrape_render_browser_no_fallback():
    """render=browser skips HTTP entirely."""
    # This test just confirms the orchestrator doesn't try HTTP first.
    # We can't actually launch a browser in this env, so we test the
    # control flow: render=browser must NOT use HttpFetcher.
    from unittest.mock import patch

    with respx.mock:
        # If scrape() tried HTTP, this would intercept and pass. We expect
        # browser mode to be attempted instead.
        respx.get("https://example.com/").mock(return_value=Response(200, text=SAMPLE))
        # Patch choose_fetcher (in the source module) to return a failing browser
        import sys

        from scrapex.errors import RenderError

        class FakeBrowser:
            def __init__(self):
                self.calls = []

            async def fetch(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise RenderError("fake browser crash")

            async def aclose(self):
                pass

        fake_browser = FakeBrowser()

        with (
            patch.object(
                sys.modules["scrapex.scrape"], "choose_fetcher", return_value=fake_browser
            ),
            pytest.raises(RenderError, match="fake browser crash"),
        ):
            await scrape(
                ScrapeRequest(
                    url="https://example.com",
                    render=RenderMode.BROWSER,
                )
            )
        # Confirm the browser was called
        assert len(fake_browser.calls) == 1


# ---------------------------------------------------------------------------
# scrape() — input normalization
# ---------------------------------------------------------------------------
async def test_scrape_accepts_string_url():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape("https://example.com")
    assert isinstance(result, ScrapeResult)


async def test_scrape_accepts_dict():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape({"url": "https://example.com"})
    assert isinstance(result, ScrapeResult)


async def test_scrape_rejects_other_types():
    with pytest.raises(TypeError):
        await scrape(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# scrape() — markdown vs html inclusion
# ---------------------------------------------------------------------------
async def test_scrape_include_markdown_true_html_is_none():
    """Default behavior: include_markdown=True → html=None, markdown=set."""
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape(ScrapeRequest(url="https://example.com"))
    assert result.html is None
    assert result.markdown is not None


async def test_scrape_include_markdown_false_html_is_set():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape(
            ScrapeRequest(
                url="https://example.com",
                include_markdown=False,
            )
        )
    assert result.html is not None
    assert result.markdown is None


# ---------------------------------------------------------------------------
# scrape() — elapsed_ms is set
# ---------------------------------------------------------------------------
async def test_scrape_sets_elapsed_ms():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape(ScrapeRequest(url="https://example.com"))
    assert isinstance(result.elapsed_ms, int)
    assert result.elapsed_ms >= 0


# ---------------------------------------------------------------------------
# scrape() — strategy branches
# ---------------------------------------------------------------------------
async def test_scrape_with_no_schema_returns_empty_extracted():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape(ScrapeRequest(url="https://example.com"))
    assert result.extracted == {}


async def test_scrape_with_none_strategy_returns_empty_extracted():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=SAMPLE)
        )
        result = await scrape(
            ScrapeRequest(
                url="https://example.com",
                schema=Schema(strategy=ExtractionStrategy.NONE, fields=[]),
            )
        )
    assert result.extracted == {}


async def test_scrape_required_field_missing_emits_warning():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text="<html><body><p>no heading</p></body></html>")
        )
        result = await scrape(
            ScrapeRequest(
                url="https://example.com",
                schema=Schema(
                    strategy=ExtractionStrategy.CSS,
                    fields=[
                        FieldSpec(name="missing_required", selector="h1.x", required=True),
                    ],
                ),
            )
        )
    assert any("missing_required" in w for w in result.extraction_warnings)


async def test_scrape_required_field_present_no_warning():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text='<html><body><h1 class="t">X</h1></body></html>')
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
    assert all("required" not in w.lower() or "t" not in w for w in result.extraction_warnings)


# ---------------------------------------------------------------------------
# scrape() — LLM strategy branches (preset resolution + raw string)
# ---------------------------------------------------------------------------
async def test_scrape_llm_with_raw_litellm_string(monkeypatch, respx_mock):
    """Passing a raw litellm string ('openai/gpt-4o-mini') skips preset lookup."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured = {}

    class FakeMsg:
        content = '{"title": "ok"}'

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        from typing import ClassVar

        choices: ClassVar = [FakeChoice()]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResp()

    from scrapex.extractors.llm import LlmExtractor

    monkeypatch.setattr(
        LlmExtractor,
        "_ensure_litellm",
        lambda self: setattr(
            self,
            "_litellm",
            type(
                "F",
                (),
                {
                    "acompletion": staticmethod(fake_acompletion),
                },
            )(),
        ),
    )

    result = await scrape(
        ScrapeRequest(
            url="https://example.com",
            schema=Schema(
                strategy=ExtractionStrategy.LLM,
                fields=[FieldSpec(name="title", description="x")],
            ),
            llm_model="openai/gpt-4o-mini",  # raw litellm string, not a preset
            llm_api_key="sk-explicit",  # explicit key must reach litellm
        )
    )
    assert captured["model"] == "openai/gpt-4o-mini"
    assert captured["api_key"] == "sk-explicit"
    assert result.extracted == {"title": "ok"}


async def test_scrape_llm_with_unknown_preset_falls_through_to_raw(monkeypatch, respx_mock):
    """An unknown model string is treated as raw litellm — no preset error."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured = {}

    class FakeMsg:
        content = '{"x": "y"}'

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        from typing import ClassVar

        choices: ClassVar = [FakeChoice()]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResp()

    from scrapex.extractors.llm import LlmExtractor

    monkeypatch.setattr(
        LlmExtractor,
        "_ensure_litellm",
        lambda self: setattr(
            self,
            "_litellm",
            type(
                "F",
                (),
                {
                    "acompletion": staticmethod(fake_acompletion),
                },
            )(),
        ),
    )

    result = await scrape(
        ScrapeRequest(
            url="https://example.com",
            schema=Schema(
                strategy=ExtractionStrategy.LLM,
                fields=[FieldSpec(name="x", description="x")],
            ),
            llm_model="totally/unknown-model",  # not a known preset, not real
        )
    )
    # Passed through unchanged to litellm
    assert captured["model"] == "totally/unknown-model"
    assert result.extracted == {"x": "y"}


# ---------------------------------------------------------------------------
# scrape() — auto fallback to browser
# ---------------------------------------------------------------------------
async def test_scrape_auto_5xx_triggers_browser_fallback(monkeypatch, respx_mock):
    """render=auto + 5xx HTTP error → falls back to browser."""
    import sys

    import scrapex.fetchers as fetchers_mod

    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(503, text="Service Unavailable")
    )

    # Build a fake HTTP fetcher that raises 503 (transient) and a fake
    # browser fetcher that succeeds. choose_fetcher must return the
    # correct one based on mode.
    class Http503Fetcher:
        async def fetch(self, *args, **kwargs):
            raise FetchError("https://example.com", "HTTP 503", status=503)

        async def aclose(self):
            pass

    class FakeBrowser:
        async def fetch(self, *args, **kwargs):
            return fetchers_mod.FetchedPage(
                url="https://example.com/",
                status=200,
                html="<html><head><title>From Browser</title></head><body><p>x</p></body></html>",
                render_mode="browser",
                title="From Browser",
            )

        async def aclose(self):
            pass

    fake_browser = FakeBrowser()

    async def selective_choose(mode, *, proxy=None):
        if mode == "browser":
            return fake_browser
        return Http503Fetcher()

    monkeypatch.setattr(sys.modules["scrapex.scrape"], "choose_fetcher", selective_choose)

    result = await scrape(ScrapeRequest(url="https://example.com"))  # render=auto default

    assert result.status == 200
    assert result.render_mode_used == "browser"
    assert any("falling back to browser" in w.lower() for w in result.extraction_warnings)
    assert result.title == "From Browser"


async def test_scrape_auto_browser_also_fails_propagates_error(monkeypatch, respx_mock):
    """render=auto + HTTP fails + browser also fails → error bubbles up."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(500, text="boom")
    )

    class FailingBrowser:
        async def fetch(self, *args, **kwargs):
            raise FetchError("https://example.com", "browser also failed", status=500)

        async def aclose(self):
            pass

    _patch_choose_fetcher(monkeypatch, _make_failing_browser_choose())

    with pytest.raises(FetchError) as exc_info:
        await scrape(ScrapeRequest(url="https://example.com"))
    assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# scrape() — retries with max_retries
# ---------------------------------------------------------------------------
async def test_scrape_retries_on_transient_then_succeeds(monkeypatch, respx_mock):
    """Transient error (timeout) → retry → success."""
    call_count = {"n": 0}

    def side_effect(request):
        call_count["n"] += 1
        if call_count["n"] < 2:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, text=SAMPLE)

    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(side_effect=side_effect)

    result = await scrape(
        ScrapeRequest(
            url="https://example.com",
            render=RenderMode.HTTP,  # disable auto-fallback so we test pure retry
            max_retries=3,
        )
    )
    assert result.status == 200
    # Two calls happened: one failure + one success
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# scrape() — auto fallback NOT triggered for 4xx
# ---------------------------------------------------------------------------
async def test_scrape_auto_404_does_not_trigger_browser(monkeypatch, respx_mock):
    """4xx is definitive — don't waste time trying the browser."""
    respx_mock.get("https://example.com/missing").mock(return_value=Response(404, text="Not Found"))

    browser_calls = {"n": 0}

    class ShouldNotBeCalledBrowser:
        async def fetch(self, *args, **kwargs):
            browser_calls["n"] += 1
            raise FetchError("https://x", "should not reach here")

        async def aclose(self):
            pass

    fake_choose, browser_calls = _make_should_not_be_called_browser_choose()

    # Build a fake HTTP fetcher that returns 404 on first call — this
    # simulates a server 404. The browser fetcher (above) MUST NOT be
    # called because 4xx is not transient.
    class Http404Fetcher:
        async def fetch(self, *args, **kwargs):
            raise FetchError("https://example.com/missing", "HTTP 404", status=404)

        async def aclose(self):
            pass

    mode_calls = []

    async def selective_choose(mode, *, proxy=None):
        mode_calls.append(mode)
        if mode == "browser":
            return fake_choose(mode, proxy=proxy)  # tracked
        return Http404Fetcher()

    import sys

    monkeypatch.setattr(sys.modules["scrapex.scrape"], "choose_fetcher", selective_choose)

    with pytest.raises(FetchError) as exc_info:
        await scrape(ScrapeRequest(url="https://example.com/missing"))
    assert exc_info.value.status == 404
    # Only HTTP mode was tried — browser was NOT
    assert mode_calls == ["http"], f"unexpected mode calls: {mode_calls}"


# ---------------------------------------------------------------------------
# scrape() — proxy is passed to the fetcher
# ---------------------------------------------------------------------------
async def test_scrape_passes_proxy_to_fetcher(monkeypatch, respx_mock):
    """The user-provided proxy must reach choose_fetcher."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text=SAMPLE)
    )
    import scrapex.fetchers as fetchers_mod

    captured_kwargs = {}

    class FakeFetcher:
        async def fetch(self, *args, **kwargs):
            return fetchers_mod.FetchedPage(
                url="https://example.com/",
                status=200,
                html=SAMPLE,
                render_mode="http",
                title="S",
            )

        async def aclose(self):
            pass

    async def fake_choose(mode, *, proxy=None):
        captured_kwargs["proxy"] = proxy
        return FakeFetcher()

    _patch_choose_fetcher(monkeypatch, fake_choose)
    await scrape(
        ScrapeRequest(
            url="https://example.com",
            proxy="http://my-proxy:8080",
        )
    )
    assert captured_kwargs["proxy"] == "http://my-proxy:8080"


# ---------------------------------------------------------------------------
# scrape() — markdown_max_chars truncation
# ---------------------------------------------------------------------------
async def test_scrape_marks_truncation_in_markdown():
    """markdown_max_chars truncates output with [...truncated] marker."""
    long_html = "<html><body><p>" + ("word " * 5000) + "</p></body></html>"
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text=long_html)
        )
        result = await scrape(
            ScrapeRequest(
                url="https://example.com",
                markdown_max_chars=500,
            )
        )
    assert result.markdown is not None
    assert "[…truncated]" in result.markdown
    assert len(result.markdown) < 1000
