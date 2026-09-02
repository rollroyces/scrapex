"""LLM extractor test — mock litellm so we never hit a real provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scrapex import ExtractionStrategy, FieldSpec, Schema
from scrapex.errors import ConfigurationError
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


async def test_llm_extractor_parses_json():
    schema = Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[
            FieldSpec(name="price", description="Numeric price in USD"),
            FieldSpec(name="in_stock", description="Whether item is in stock"),
        ],
    )
    mock_litellm = AsyncMock()
    mock_litellm.acompletion = AsyncMock(
        return_value=FakeResponse('{"price": "$42.50", "in_stock": true}')
    )
    extractor = LlmExtractor()
    extractor._litellm = mock_litellm
    out = await extractor.extract(
        "<html><body>Price is $42.50, in stock.</body></html>",
        schema,
        llm_model="gpt-4o-mini",
    )
    assert out == {"price": "$42.50", "in_stock": True}


async def test_llm_extractor_requires_model():
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x")])
    extractor = LlmExtractor()
    extractor._litellm = AsyncMock()  # pretend litellm is installed
    with pytest.raises(ConfigurationError):
        await extractor.extract("<p>x</p>", schema)


async def test_llm_extractor_missing_dep_raises():
    """Without litellm installed, give a clear error."""
    extractor = LlmExtractor()
    extractor._litellm = None
    with (
        patch.dict("sys.modules", {"litellm": None}),
        pytest.raises(ConfigurationError, match="llm"),
    ):
        extractor._ensure_litellm()


async def test_llm_extractor_bad_json_raises():
    schema = Schema(strategy=ExtractionStrategy.LLM, fields=[FieldSpec(name="x", description="x")])
    mock_litellm = AsyncMock()
    mock_litellm.acompletion = AsyncMock(return_value=FakeResponse("not json at all"))
    extractor = LlmExtractor()
    extractor._litellm = mock_litellm
    from scrapex.errors import ExtractionError

    with pytest.raises(ExtractionError):
        await extractor.extract("<p>x</p>", schema, llm_model="gpt-4o-mini")
