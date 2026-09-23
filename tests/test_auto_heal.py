"""Tests for the auto-heal behavior in scrape().

Auto-heal is opt-in (default ON). When enabled, scrape() detects
"extraction returned empty for all fields" and calls Schema.heal()
once to patch the schema, then re-extracts.

Hard cap: 1 retry. No recursion (preserves the single-page contract).

Quadrants covered:
  1. Extraction succeeds -> no heal
  2. Extraction empty, heal fixes it -> re-extract succeeds + warning
  3. Extraction empty, heal returns identical schema -> no extra warning
  4. auto_heal=False -> no heal call
  5. LLM strategy -> heal skipped (LLM is the extractor itself)
  6. Heal raises -> warning + original empty result, no crash
  7. No schema -> no heal trigger
  8. Partial extraction (some fields filled) -> no heal trigger
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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

SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
    <h1 class="title">Hello World</h1>
    <div class="price">$42.50</div>
</body>
</html>
"""

# The "broken" schema targets classes that don't exist in SAMPLE_HTML.
# Auto-heal should patch them to the real classes (title + price).
BROKEN_SCHEMA = Schema(
    strategy=ExtractionStrategy.CSS,
    fields=[
        FieldSpec(name="title", selector="h1.OLD-CLASS-NOPE"),
        FieldSpec(name="price", selector="span.OLD-PRICE-NOPE"),
    ],
)

WORKING_SCHEMA = Schema(
    strategy=ExtractionStrategy.CSS,
    fields=[
        FieldSpec(name="title", selector="h1.title"),
        FieldSpec(name="price", selector="div.price"),
    ],
)


class _HealPatch:
    """Context manager that patches _get_litellm and exposes the mock.

    Usage:
        with _HealPatch([]) as p:
            ... p.mock_litellm.completion.call_count ...
    """

    def __init__(self, fixed_fields: list[FieldSpec]) -> None:
        mock_litellm = MagicMock()
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "fixes": [
                    {"name": f.name, "selector": f.selector, "reason": "test"}
                    for f in fixed_fields
                ]
            }
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=msg)]
        mock_litellm.completion = MagicMock(return_value=mock_response)
        self.mock_litellm = mock_litellm
        self._patch = patch(
            "scrapex.schema_synth._get_litellm", return_value=mock_litellm
        )

    def __enter__(self) -> _HealPatch:
        self._patch.__enter__()
        return self

    def __exit__(  # type: ignore[no-untyped-def]
        self, exc_type, exc_value, traceback
    ) -> None:
        self._patch.__exit__(exc_type, exc_value, traceback)


# ---------------------------------------------------------------------------
# Quadrant 1: Extraction succeeds -> no heal call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_not_triggered_on_success():
    """Working schema extracts correctly. Heal is never called."""
    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        with _HealPatch([]) as p:
            req = ScrapeRequest(
                url="https://test.example/",
                schema=WORKING_SCHEMA,
                llm_model="test-model",
            )
            result = await scrape(req)

    assert result.extracted["title"] == "Hello World"
    assert result.extracted["price"] == "$42.50"
    assert not any("auto-healed" in w for w in result.extraction_warnings)
    assert p.mock_litellm.completion.call_count == 0, (
        "heal was called but extraction was successful"
    )


# ---------------------------------------------------------------------------
# Quadrant 2: Extraction empty + heal fixes it -> re-extract + warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_triggers_on_empty_extraction():
    """Broken schema extracts empty -> heal patches -> re-extract succeeds."""
    fixed = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.title"),
            FieldSpec(name="price", selector="div.price"),
        ],
    )
    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        with _HealPatch(fixed.fields) as p:
            req = ScrapeRequest(
                url="https://test.example/",
                schema=BROKEN_SCHEMA,
                llm_model="test-model",
            )
            result = await scrape(req)

    # Heal was called once
    assert p.mock_litellm.completion.call_count == 1
    # Re-extract succeeded
    assert result.extracted["title"] == "Hello World"
    assert result.extracted["price"] == "$42.50"
    # Warning fired
    assert any("auto-healed" in w for w in result.extraction_warnings)


# ---------------------------------------------------------------------------
# Quadrant 3: Extraction empty + heal returns identical schema -> no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_no_warning_when_heal_returns_same_schema():
    """If heal can't fix anything, no extra warning, original empty result.

    This is the "LLM didn't know what to fix" case -- we should be quiet
    about it because the user already has the original empty extraction.
    """
    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        # heal returns NO fixes (empty fixes list)
        with _HealPatch([]) as p:
            req = ScrapeRequest(
                url="https://test.example/",
                schema=BROKEN_SCHEMA,
                llm_model="test-model",
            )
            result = await scrape(req)

    assert p.mock_litellm.completion.call_count == 1, "heal was tried"
    # No values extracted
    assert not any(result.extracted.values())
    # No "auto-healed" warning (LLM didn't actually fix anything)
    assert not any("auto-healed" in w for w in result.extraction_warnings)


# ---------------------------------------------------------------------------
# Quadrant 4: auto_heal=False -> no heal call at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_disabled_skips_heal():
    """When auto_heal=False, heal is never called even on empty extraction."""
    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        with _HealPatch([]) as p:
            req = ScrapeRequest(
                url="https://test.example/",
                schema=BROKEN_SCHEMA,
                auto_heal=False,
            )
            result = await scrape(req)

    assert p.mock_litellm.completion.call_count == 0
    assert not any(result.extracted.values())
    assert not any("auto-healed" in w for w in result.extraction_warnings)


# ---------------------------------------------------------------------------
# Quadrant 5: LLM strategy -> heal skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_skipped_for_llm_strategy():
    """LLM strategy is already LLM-driven; heal would be redundant.

    Empty extraction from an LLM means the page didn't have the data,
    not that the schema is broken.
    """
    from scrapex.extractors.llm import LlmExtractor

    async def fake_extract(self, html, schema, **_kw):
        return {}

    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        with _HealPatch([]) as p, patch.object(LlmExtractor, "extract", new=fake_extract):
            req = ScrapeRequest(
                url="https://test.example/",
                schema=Schema(
                    strategy=ExtractionStrategy.LLM,
                    fields=[FieldSpec(name="title", selector="ignored")],
                ),
                llm_model="test-model",
            )
            result = await scrape(req)

    assert p.mock_litellm.completion.call_count == 0, (
        "heal was called for LLM strategy"
    )
    assert not any(result.extracted.values())


# ---------------------------------------------------------------------------
# Quadrant 6: Heal raises -> warning + original empty result, no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_failure_does_not_crash():
    """If heal() raises (e.g. LLM unreachable), we get a warning + empty result.

    The user's call must not crash just because the recovery attempt failed.
    """
    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        # Mock heal to raise
        with patch.object(
            Schema, "heal", side_effect=RuntimeError("LLM unreachable")
        ):
            req = ScrapeRequest(
                url="https://test.example/",
                schema=BROKEN_SCHEMA,
                llm_model="test-model",
            )
            # Must not raise
            result = await scrape(req)

    # Original empty result preserved
    assert not any(result.extracted.values())
    # Warning surfaced
    assert any("auto-heal failed" in w for w in result.extraction_warnings)
    assert any("RuntimeError" in w for w in result.extraction_warnings)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_heal_skipped_when_no_schema():
    """No schema means no extraction -> no heal trigger."""
    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        with _HealPatch([]) as p:
            req = ScrapeRequest(url="https://test.example/")
            result = await scrape(req)

    assert p.mock_litellm.completion.call_count == 0
    assert not result.extracted


@pytest.mark.asyncio
async def test_auto_heal_skipped_when_extraction_partial():
    """Partial extraction (some fields filled) is NOT a heal trigger.

    "Some data" means the schema mostly works. Heal might still help
    fill the missing fields, but we'd risk corrupting the working ones.
    Conservative call: don't auto-heal.
    """
    from scrapex.extractors.css import CssExtractor

    async def fake_extract(self, html, schema, **_kw):
        return {"title": "Hello World"}  # price is missing

    with respx.mock(base_url="https://test.example") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        with _HealPatch([]) as p, patch.object(CssExtractor, "extract", new=fake_extract):
            req = ScrapeRequest(
                url="https://test.example/",
                schema=BROKEN_SCHEMA,
                llm_model="test-model",
            )
            result = await scrape(req)

    assert p.mock_litellm.completion.call_count == 0, (
        "heal triggered on partial extraction (false positive)"
    )
    assert result.extracted["title"] == "Hello World"
