"""Real-website heal tests using recorded HTML fixtures.

Unlike test_heal_live.py which is fully mocked, this file uses
real HTML recorded from real websites (Wikipedia, httpbin, example.com).
The fixtures are served by an in-process HTTP server so we get
real HTTP behavior without flakiness.

Run:
    pytest tests/integration/test_heal_real_websites.py -v

These tests work WITHOUT an API key — they use the fixture HTML
and verify heal's local behavior (asserts, schema structure).
The heal() function itself is mocked so we test the integration
shape, not the LLM quality.

For the LLM-quality test, see test_heal_live.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# --- Sanity checks: fixtures exist --------------------------------------


def test_fixtures_dir_exists(fixtures_dir):
    """The fixtures directory is set up correctly."""
    assert fixtures_dir.exists(), f"missing fixtures dir: {fixtures_dir}"
    html_files = list(fixtures_dir.glob("*.html"))
    assert len(html_files) >= 2, (
        f"expected at least 2 HTML fixtures, found {len(html_files)}: "
        f"{[f.name for f in html_files]}"
    )


def test_fixture_server_starts(fixture_server):
    """The fixture server responds to GET requests on a real port."""
    import urllib.request

    url = f"{fixture_server.base_url}/example-com.html"
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read()
    assert len(body) > 100
    assert b"Example Domain" in body


def test_fixture_server_returns_404(fixture_server):
    """Unknown paths return 404."""
    import urllib.error
    import urllib.request

    url = f"{fixture_server.base_url}/does-not-exist.html"
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(url, timeout=5)
    assert exc_info.value.code == 404


def test_fixture_server_serves_wikipedia(fixture_server):
    """The Wikipedia fixture is large and contains the expected content."""
    import urllib.request

    url = f"{fixture_server.base_url}/wikipedia-python.html"
    with urllib.request.urlopen(url, timeout=10) as resp:
        body = resp.read()
    # Wikipedia fixture is ~1MB
    assert len(body) > 100_000
    # Should contain "Python" many times
    assert body.count(b"Python") > 50


# --- Heal integration: example.com --------------------------------------


def test_heal_handles_example_com_realisticly(fixture_server):
    """End-to-end: fetch the example.com HTML via the fixture server,
    build a broken schema, mock the LLM to return a fix, verify the
    schema is now usable on the real HTML."""
    import urllib.request

    from scrapex import FieldSpec, Schema
    from scrapex.models import ExtractionStrategy

    # Fetch the real HTML
    url = f"{fixture_server.base_url}/example-com.html"
    with urllib.request.urlopen(url, timeout=5) as resp:
        html = resp.read().decode("utf-8")

    # Build a broken schema (simulating a redesign)
    broken = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.OLD-title-2024"),
        ],
    )

    # Mock the LLM to return a sensible fix
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    msg = MagicMock()
    msg.content = '{"fixes": [{"name": "title", "selector": "title", "reason": "use the title tag"}]}'
    mock_response.choices = [mock_response.choices[0].__class__()] if False else [MagicMock(message=msg)]
    mock_litellm = MagicMock()
    mock_litellm.completion = MagicMock(return_value=mock_response)

    with patch("scrapex.schema_synth._get_litellm", return_value=mock_litellm):
        healed = broken.heal(html, llm_model="test-model")

    # Verify the healed selector actually matches the real HTML
    by_name = {f.name: f for f in healed.fields}
    assert by_name["title"].selector == "title"
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    el = soup.select_one(by_name["title"].selector)
    assert el is not None
    assert "Example Domain" in el.get_text()


# --- Heal against httpbin HTML ------------------------------------------


def test_heal_handles_httpbin_realisticly(fixture_server):
    """End-to-end against httpbin's HTML fixture (Herman Melville quote)."""
    import urllib.request

    from scrapex import FieldSpec, Schema
    from scrapex.models import ExtractionStrategy

    url = f"{fixture_server.base_url}/httpbin-html.html"
    with urllib.request.urlopen(url, timeout=5) as resp:
        html = resp.read().decode("utf-8")

    broken = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="heading", selector="h1.OLD-class"),
            FieldSpec(name="first_para", selector="p.OLD-class"),
        ],
    )

    from unittest.mock import MagicMock
    mock_litellm = MagicMock()
    mock_response = MagicMock()
    msg = MagicMock()
    msg.content = '{"fixes": [{"name": "heading", "selector": "h1", "reason": "h1 is the heading"}, {"name": "first_para", "selector": "p", "reason": "first paragraph"}]}'
    mock_response.choices = [MagicMock(message=msg)]
    mock_litellm.completion = MagicMock(return_value=mock_response)

    with patch("scrapex.schema_synth._get_litellm", return_value=mock_litellm):
        healed = broken.heal(html, llm_model="test-model")

    by_name = {f.name: f for f in healed.fields}
    # Both selectors should be patched
    assert by_name["heading"].selector == "h1"
    assert by_name["first_para"].selector == "p"

    # Verify against real HTML
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    assert soup.select_one(by_name["heading"].selector) is not None
    assert soup.select_one(by_name["first_para"].selector) is not None


# --- End-to-end: full scrape + heal loop -------------------------------


@pytest.mark.asyncio
async def test_scrape_then_heal_loop(fixture_server):
    """The realistic workflow:
    1. Fetch a page (via fetchers) — gets real HTML
    2. Try to extract with a saved schema — gets empty result
    3. Heal the schema with the fetched HTML
    4. Re-extract with the healed schema — succeeds

    This is the "site redesigned" recovery flow.
    """
    import urllib.request

    url = f"{fixture_server.base_url}/example-com.html"
    with urllib.request.urlopen(url, timeout=5) as resp:
        html = resp.read().decode("utf-8")

    from scrapex import FieldSpec, Schema
    from scrapex.models import ExtractionStrategy

    # 1. User has a saved schema with old selectors
    saved = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.OLD-class-2024"),
        ],
    )

    # 2. Try to apply the saved schema — won't match (h1 doesn't exist)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    assert soup.select_one(saved.fields[0].selector) is None  # broken

    # 3. Heal with the real HTML
    from unittest.mock import MagicMock
    mock_litellm = MagicMock()
    mock_response = MagicMock()
    msg = MagicMock()
    msg.content = '{"fixes": [{"name": "title", "selector": "title", "reason": "use title tag"}]}'
    mock_response.choices = [MagicMock(message=msg)]
    mock_litellm.completion = MagicMock(return_value=mock_response)

    with patch("scrapex.schema_synth._get_litellm", return_value=mock_litellm):
        healed = saved.heal(html, llm_model="test-model")

    # 4. Apply the healed schema — should now work
    el = soup.select_one(healed.fields[0].selector)
    assert el is not None
    assert "Example Domain" in el.get_text()
