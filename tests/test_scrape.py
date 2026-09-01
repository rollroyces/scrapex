"""Smoke + unit tests.

Real HTTP calls (example.com, httpbin) verify end-to-end. The LLM extractor
is tested with a mocked litellm — never hits a real provider in CI.
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

SAMPLE_HTML = """
<html>
<head>
    <title>Test Page</title>
</head>
<body>
    <h1 class="title">Hello World</h1>
    <div class="price" data-amount="42.50">$42.50</div>
    <p class="desc">A short description.</p>
</body>
</html>
"""


@pytest.fixture
def html_server(respx_mock):
    """Mock httpx so tests don't touch the network.

    NOTE: respx matches by URL prefix — ``https://example.com`` matches
    ``https://example.com/missing``. Use exact paths (``url=...``) for
    non-root URLs and a regex for the bare-host case.
    """
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text=SAMPLE_HTML)
    )
    respx_mock.get(url="https://example.com/missing").mock(
        return_value=Response(404, text="Not Found")
    )
    return respx_mock


async def test_scrape_basic_html_to_markdown(html_server):
    req = ScrapeRequest(url="https://example.com")
    result = await scrape(req)
    assert result.status == 200
    assert result.title == "Test Page"
    assert result.markdown is not None
    assert "Hello World" in result.markdown
    assert result.extracted == {}  # no schema → empty


async def test_scrape_css_extraction(html_server):
    req = ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.CSS,
            fields=[
                FieldSpec(name="title", selector="h1.title"),
                FieldSpec(name="price", selector="div.price", attr="data-amount"),
                FieldSpec(
                    name="missing_required",
                    selector="h2.does-not-exist",
                    required=True,
                ),
            ],
        ),
    )
    result = await scrape(req)
    assert result.extracted["title"] == "Hello World"
    assert result.extracted["price"] == "42.50"
    assert result.extracted["missing_required"] is None
    # Required field missing → warning should fire
    assert any("missing_required" in w for w in result.extraction_warnings)


async def test_scrape_xpath_extraction(html_server):
    req = ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.XPATH,
            fields=[FieldSpec(name="title", selector="//h1")],
        ),
    )
    result = await scrape(req)
    assert result.extracted["title"] == "Hello World"


async def test_scrape_regex_extraction(html_server):
    req = ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.REGEX,
            fields=[
                FieldSpec(name="amount", selector=r"\$(\d+\.\d{2})"),
                FieldSpec(name="word", selector=r"(Hello)\s+(World)"),
            ],
        ),
    )
    result = await scrape(req)
    assert result.extracted["amount"] == "42.50"
    assert result.extracted["word"] == "Hello"


async def test_scrape_404_raises(html_server):
    req = ScrapeRequest(url="https://example.com/missing")
    with pytest.raises(FetchError) as excinfo:
        await scrape(req)
    assert excinfo.value.status == 404


async def test_scrape_accepts_string():
    """Convenience: passing a bare URL works."""
    with respx.mock:
        respx.get("https://example.com").mock(return_value=Response(200, text=SAMPLE_HTML))
        result = await scrape("https://example.com")
    assert result.title == "Test Page"


async def test_scrape_accepts_dict():
    with respx.mock:
        respx.get("https://example.com").mock(return_value=Response(200, text=SAMPLE_HTML))
        result = await scrape({"url": "https://example.com"})
    assert result.title == "Test Page"


def test_html_to_markdown_strips_scripts():
    html = "<p>hello</p><script>evil()</script><style>body{}</style><p>world</p>"
    md = html_to_markdown(html)
    assert "evil" not in md
    assert "hello" in md and "world" in md


def test_chunk_markdown_splits_paragraphs():
    md = "## A\n\npara1\n\npara2\n\npara3\n\n" * 20
    chunks = chunk_markdown(md, max_chars=200, overlap=20)
    assert len(chunks) > 1
    # Overlap ensures continuity
    assert any("para" in c for c in chunks)


def test_chunk_markdown_empty():
    assert chunk_markdown("") == []
