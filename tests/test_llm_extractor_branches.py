"""Tests for the LLM extractor — every branch in extractors/llm.py.

Covers:
- api_base parameter (passes through to litellm)
- api_key=None falls through to litellm env-var discovery
- Markdown truncation when content > 100K
- HTML truncation when no markdown supplied
- Schema field description vs name fallback
- Unknown field returned by LLM is silently dropped
- Empty content
- Empty schema.fields (no extraction happens)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from scrapex import ExtractionStrategy, FieldSpec, Schema
from scrapex.errors import ConfigurationError, ExtractionError
from scrapex.extractors.llm import LlmExtractor


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]


def _make_extractor(acompletion_mock):
    """Create an LlmExtractor with mocked litellm — no real API calls."""
    ext = LlmExtractor()
    mock_litellm = AsyncMock()
    mock_litellm.acompletion = acompletion_mock
    ext._litellm = mock_litellm
    return ext, mock_litellm


async def test_llm_passes_api_base_to_litellm():
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    await ext.extract(
        "<p>hi</p>",
        schema,
        llm_model="gpt-4o-mini",
        api_base="http://my-proxy.example.com/v1",
    )
    assert captured["api_base"] == "http://my-proxy.example.com/v1"


async def test_llm_omits_api_base_when_not_provided():
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert "api_base" not in captured


async def test_llm_omits_api_key_when_not_provided():
    """If user didn't pass llm_api_key, don't pass api_key=None to litellm —
    let litellm fall through to its own env-var discovery."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert "api_key" not in captured


async def test_llm_includes_api_key_when_provided():
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    await ext.extract(
        "<p>hi</p>",
        schema,
        llm_model="gpt-4o-mini",
        llm_api_key="sk-test",
    )
    assert captured["api_key"] == "sk-test"


async def test_llm_truncates_oversized_markdown():
    """When markdown > 100K chars, gets truncated with [...truncated] marker."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    big_markdown = "x" * 200_000
    await ext.extract(
        "<html>short</html>",
        schema,
        llm_model="gpt-4o-mini",
        markdown=big_markdown,
    )
    # The prompt content sent to litellm must contain [...truncated]
    user_message = captured["messages"][0]["content"]
    assert "[...truncated]" in user_message
    # And it must be shorter than the original
    assert len(user_message) < len(big_markdown)


async def test_llm_falls_back_to_html_when_no_markdown():
    """When no markdown is provided, raw HTML is sent (also truncated if > 100K)."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    big_html = "<p>" + "x" * 200_000 + "</p>"
    await ext.extract(big_html, schema, llm_model="gpt-4o-mini")
    user_message = captured["messages"][0]["content"]
    assert "[...truncated]" in user_message


async def test_llm_uses_field_name_when_no_description():
    """FieldSpec with no description uses name as the description in the prompt."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"my_field": "value"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[FieldSpec(name="my_field")],  # no description
    )
    out = await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert out == {"my_field": "value"}
    # The prompt should mention the field name as its own description
    user_message = captured["messages"][0]["content"]
    assert "my_field" in user_message


async def test_llm_drops_fields_not_in_schema():
    """LLM might return extra fields — only keep the ones in the schema."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"title": "ok", "extra": "ignored", "another": "also ignored"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[FieldSpec(name="title", description="title")],
    )
    out = await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert out == {"title": "ok"}
    assert "extra" not in out
    assert "another" not in out


async def test_llm_with_empty_schema_fields():
    """Schema with no fields → empty result, but LLM call still happens."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse("{}")

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[])
    out = await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert out == {}


async def test_llm_uses_response_format_json_object():
    """LLM call must request JSON mode for reliable parsing."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["temperature"] == 0


async def test_llm_uses_markdown_over_html_when_both_provided():
    """If markdown is passed, use it (cleaner) instead of raw HTML."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"x": "y"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    await ext.extract(
        "<html>RAW HTML</html>",
        schema,
        llm_model="gpt-4o-mini",
        markdown="CLEAN MARKDOWN",
    )
    user_message = captured["messages"][0]["content"]
    assert "CLEAN MARKDOWN" in user_message
    assert "RAW HTML" not in user_message


async def test_llm_returns_none_for_missing_schema_fields():
    """If LLM omits a schema field, the result has it as None (not KeyError)."""
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse('{"only_one": "value"}')

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[
            FieldSpec(name="only_one", description="x"),
            FieldSpec(name="missing", description="y"),
        ],
    )
    out = await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert out == {"only_one": "value", "missing": None}


async def test_llm_propagates_litellm_exception_as_extraction_error():
    async def fake_acompletion(**kwargs):
        raise RuntimeError("connection refused")

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    with pytest.raises(ExtractionError, match="connection refused"):
        await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")


async def test_llm_raises_configuration_error_when_no_model():
    """No llm_model → clean ConfigurationError, not AttributeError."""
    ext, _ = _make_extractor(AsyncMock(return_value=FakeResponse("{}")))
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    with pytest.raises(ConfigurationError, match="llm_model"):
        await ext.extract("<p>hi</p>", schema)


def test_llm_ensure_litellm_when_already_loaded():
    """_ensure_litellm is a no-op if _litellm is already set."""
    ext = LlmExtractor()
    sentinel = object()
    ext._litellm = sentinel  # type: ignore[assignment]
    ext._ensure_litellm()
    assert ext._litellm is sentinel


def test_llm_ensure_litellm_actually_imports_litellm():
    """Fresh instance → first _ensure_litellm call imports and assigns litellm."""
    from scrapex.extractors.llm import LlmExtractor

    ext = LlmExtractor()
    assert ext._litellm is None  # sanity: not pre-loaded
    ext._ensure_litellm()
    # Now _litellm is the real litellm module
    import litellm

    assert ext._litellm is litellm


async def test_llm_handles_empty_response():
    """LLM returns empty string content → empty dict, no crash."""

    async def fake_acompletion(**kwargs):
        return FakeResponse("")

    ext, _ = _make_extractor(fake_acompletion)
    schema = Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[FieldSpec(name="x", description="x")],
    )
    out = await ext.extract("<p>hi</p>", schema, llm_model="gpt-4o-mini")
    assert out == {"x": None}
