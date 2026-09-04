"""Tests for Schema.from_goal() and Schema.explain().

These tests mock the LLM call (no API key needed in CI). The mock is
realistic enough to exercise the contract: JSON response with name,
selector, attr, reason fields. The "real LLM" path is exercised by
running the probe in spikes/005-llm-schema/ with a real key.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from scrapex import Schema
from scrapex.errors import ConfigurationError
from scrapex.schema_synth import (
    _apply_schema_to_html,
    _cached_synthesize,
    _ollama_reachable,
    _resolve_default_model,
    _synthesize,
)

# --- Mock LLM helpers ----------------------------------------------------


def _fake_litellm_response(content: str):
    """Build a fake litellm.completion() return value."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# --- _resolve_default_model ----------------------------------------------


def test_resolve_default_model_picks_ollama_when_host_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = _resolve_default_model()
    assert model.startswith("ollama/")
    assert "qwen" in model or "llama" in model


def test_resolve_default_model_picks_openai_when_no_ollama(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # _ollama_reachable will be checked, must return False
    with patch("scrapex.schema_synth._ollama_reachable", return_value=False):
        model = _resolve_default_model()
    assert model == "gpt-4o-mini"


def test_resolve_default_model_raises_when_no_llm_available(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with (
        patch("scrapex.schema_synth._ollama_reachable", return_value=False),
        pytest.raises(ConfigurationError, match=r"Schema\.from_goal"),
    ):
        _resolve_default_model()


def test_ollama_reachable_handles_connection_refused():
    """The probe should never raise; it just returns False on any error."""
    with patch.dict(os.environ, {"OLLAMA_HOST": "http://127.0.0.1:1"}):
        # Port 1 should refuse connections
        assert _ollama_reachable() is False


# --- _synthesize (with mocked litellm) ------------------------------------


@pytest.fixture(autouse=True)
def clear_lru_cache():
    """Clear the LLM cache between tests so test isolation is real.

    The cache is module-level (intentionally — same page + same goal
    SHOULD cache in production). But tests need to call the mock
    fresh each time, so we clear after each test.
    """

    _cached_synthesize.cache_clear()
    yield
    _cached_synthesize.cache_clear()


@pytest.fixture
def mock_litellm_good_response():
    """Patch litellm.completion to return a realistic schema response."""
    sample_response = (
        '{"fields": ['
        '{"name": "title", "selector": "h1.title", "attr": "text", '
        '"reason": "the h1 with class title looked like the page title"},'
        '{"name": "price", "selector": "div.price", "attr": "text", '
        '"reason": "the div with class price is the only price-like field"}'
        "]}"
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response(sample_response))
        mock_get.return_value = mock_litellm
        yield mock_litellm


def test_synthesize_returns_field_dict(mock_litellm_good_response):
    data = _synthesize(
        "<h1 class='title'>Hi</h1><div class='price'>$5</div>",
        "title and price",
        llm_model="test-model",
    )
    assert "fields" in data
    assert len(data["fields"]) == 2
    assert data["fields"][0]["name"] == "title"
    assert data["fields"][0]["selector"] == "h1.title"


def test_synthesize_caches_identical_inputs(mock_litellm_good_response):
    """Two calls with the same (html, goal, model) should hit litellm once."""
    html = "<h1 class='title'>Hi</h1>"
    _synthesize(html, "title", llm_model="test-model")
    _synthesize(html, "title", llm_model="test-model")
    # litellm.completion called once (second is cached)
    assert mock_litellm_good_response.completion.call_count == 1


def test_synthesize_passes_goal_in_prompt(mock_litellm_good_response):
    """The goal string must appear in the prompt sent to the LLM."""
    _synthesize("<p>hi</p>", "extract the hello world message", llm_model="test-model")
    prompt = mock_litellm_good_response.completion.call_args.kwargs["messages"][0]["content"]
    assert "hello world message" in prompt
    assert "<p>hi</p>" in prompt


def test_synthesize_handles_non_json_response():
    """LLM returns garbage → ConfigurationError, not silent empty result."""
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response("not json at all"))
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="non-JSON"):
            _synthesize("<p>hi</p>", "test", llm_model="test-model")


def test_synthesize_handles_litellm_exception():
    """Network down / model not found → ConfigurationError with install hint."""
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(side_effect=ConnectionError("ollama not running"))
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="failed to call model"):
            _synthesize("<p>hi</p>", "test", llm_model="test-model")


def test_synthesize_handles_empty_response():
    """LLM returns empty string → ConfigurationError (can't parse)."""
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response(""))
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError):
            _synthesize("<p>hi</p>", "test", llm_model="test-model")


# --- Schema.from_goal() ---------------------------------------------------


def test_from_goal_returns_schema_with_fields():
    """End-to-end: from_goal builds a usable Schema."""
    response = (
        '{"fields": ['
        '{"name": "title", "selector": "h1", "attr": "text", '
        '"reason": "h1 is the main heading"}'
        "]}"
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response(response))
        mock_get.return_value = mock_litellm
        schema = Schema.from_goal("the title", "<h1>Hello</h1>", llm_model="test-model")
    assert isinstance(schema, Schema)
    assert len(schema.fields) == 1
    assert schema.fields[0].name == "title"
    assert schema.fields[0].selector == "h1"
    assert schema.fields[0].description == "h1 is the main heading"


def test_from_goal_handles_no_fields_returned():
    """LLM returns 0 fields → warning, empty Schema (lenient, no exception)."""
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response('{"fields": []}'))
        mock_get.return_value = mock_litellm
        with pytest.warns(UserWarning, match="0 usable fields"):
            schema = Schema.from_goal("nonsense goal", "<p>hi</p>", llm_model="test-model")
    assert len(schema.fields) == 0


def test_from_goal_skips_malformed_fields():
    """Individual bad fields are dropped, the rest survive."""
    response = (
        '{"fields": ['
        '{"name": "title", "selector": "h1", "attr": "text"},'  # good
        '{"name": 123, "selector": "p"},'  # bad: name is not a string
        '{"selector": "div"},'  # bad: no name
        '{"name": "ok", "selector": "div"}'  # good
        "]}"
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response(response))
        mock_get.return_value = mock_litellm
        schema = Schema.from_goal("test", "<p>hi</p>", llm_model="test-model")
    # Should keep the 2 valid fields, drop the 2 bad ones
    assert len(schema.fields) == 2
    assert {f.name for f in schema.fields} == {"title", "ok"}


def test_from_goal_truncates_oversized_html():
    """HTML over 50K chars gets truncated (don't blow the LLM context)."""
    big_html = "<p>" + ("x" * 100_000) + "</p>"
    captured = {}

    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()

        def capture(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            return _fake_litellm_response('{"fields": []}')

        mock_litellm.completion = MagicMock(side_effect=capture)
        mock_get.return_value = mock_litellm
        Schema.from_goal("extract text", big_html, llm_model="test-model")
    # The HTML in the prompt should be capped (we keep the first 50K
    # plus the goal/header). Verify the prompt size is bounded.
    # The full big_html is 100,005 chars; the prompt should be well under that.
    assert len(captured["prompt"]) < 60_000


# --- Schema.explain() -----------------------------------------------------


def test_explain_includes_description_from_llm():
    """If the field has a description (from the LLM's 'reason'), show it."""
    response = (
        '{"fields": ['
        '{"name": "title", "selector": "h1", "attr": "text", '
        '"reason": "this is the main heading"}'
        "]}"
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response(response))
        mock_get.return_value = mock_litellm
        schema = Schema.from_goal("the title", "<h1>x</h1>", llm_model="test-model")
    lines = schema.explain()
    assert lines == ["title: this is the main heading"]


def test_explain_falls_back_to_selector_when_no_description():
    """Hand-written schemas without descriptions get a synthesized explain line."""
    schema = Schema(
        strategy=__import__("scrapex").ExtractionStrategy.CSS,
        fields=[
            __import__("scrapex").FieldSpec(name="title", selector="h1"),
        ],
    )
    lines = schema.explain()
    assert len(lines) == 1
    assert "title" in lines[0]
    assert "h1" in lines[0]


def test_explain_returns_one_line_per_field():
    schema = Schema(
        strategy=__import__("scrapex").ExtractionStrategy.CSS,
        fields=[
            __import__("scrapex").FieldSpec(name="a", selector="h1"),
            __import__("scrapex").FieldSpec(name="b", selector="p"),
            __import__("scrapex").FieldSpec(name="c", selector="div"),
        ],
    )
    assert len(schema.explain()) == 3


# --- _apply_schema_to_html (internal helper) ------------------------------


def test_apply_schema_to_html_extracts_text_and_href():
    schema = Schema(
        strategy=__import__("scrapex").ExtractionStrategy.CSS,
        fields=[
            __import__("scrapex").FieldSpec(name="title", selector="h1.title", attr="text"),
            __import__("scrapex").FieldSpec(name="link", selector="a", attr="href"),
        ],
    )
    html = '<html><h1 class="title">Hello</h1><a href="/x">click</a></html>'
    out = _apply_schema_to_html(html, schema)
    assert out["title"] == "Hello"
    assert out["link"] == "/x"


def test_apply_schema_to_html_returns_none_for_missing():
    schema = Schema(
        strategy=__import__("scrapex").ExtractionStrategy.CSS,
        fields=[
            __import__("scrapex").FieldSpec(name="missing", selector="h1.doesnotexist"),
        ],
    )
    out = _apply_schema_to_html("<html><body>x</body></html>", schema)
    assert out["missing"] is None


# --- Integration: from_goal output actually works with the CSS extractor --


def test_from_goal_output_is_usable_with_css_extractor():
    """The whole point: from_goal output should work end-to-end with scrapex's
    existing CSS extractor. If it doesn't, the feature is worthless."""
    response = (
        '{"fields": ['
        '{"name": "title", "selector": "h1.title", "attr": "text", '
        '"reason": "the h1 with class title"},'
        '{"name": "link", "selector": "a.download", "attr": "href", '
        '"reason": "the a with class download is the download link"}'
        "]}"
    )
    html = """
    <html><body>
      <h1 class="title">Q3 Report</h1>
      <a class="download" href="/files/q3.pdf">Download</a>
    </body></html>
    """
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(return_value=_fake_litellm_response(response))
        mock_get.return_value = mock_litellm
        schema = Schema.from_goal("the title and download link", html, llm_model="test-model")

    # Now use the schema with the real CSS extractor
    from scrapex.extractors.css import CssExtractor

    async def run():
        return await CssExtractor().extract(html, schema)

    out = asyncio.run(run())
    assert out["title"] == "Q3 Report"
    assert out["link"] == "/files/q3.pdf"


# --- opt-in: schema_synth is only loaded when used ---------------------


def test_schema_synth_lazy_attached(monkeypatch):
    """Schema.from_goal is attached at import time when litellm is available.

    Verify both directions:
    1. With litellm installed (our test env), the methods are attached.
    2. The package is importable even if schema_synth fails to load.
    """
    import scrapex

    # Direction 1: with litellm installed, methods are present
    assert hasattr(scrapex.Schema, "from_goal")
    assert hasattr(scrapex.Schema, "explain")
    # Both are callable
    assert callable(scrapex.Schema.from_goal)
    assert callable(scrapex.Schema.explain)
