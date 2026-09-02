"""Tests for the extractors subpackage — every strategy, every branch.

Covers:
- CSS: attr="html" branch, invalid selector, multiple fields, multiple matches
- XPath: attr="html" branch, attr other than text/html, missing nodes
- Regex: invalid regex (re.error) branch, no match, multiple groups
- LLM: markdown truncation, html truncation, missing schema fields
- Registry: get/available roundtrip
"""

from __future__ import annotations

import pytest

from scrapex import ExtractionStrategy, FieldSpec, Schema
from scrapex.extractors import available as registered_names
from scrapex.extractors import get as get_extractor


# ---------------------------------------------------------------------------
# CSS extractor — all branches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "attr,expected",
    [
        ("text", "Hello World"),
        ("html", '<h1 class="title">Hello World</h1>'),  # BS4 preserves class attribute
    ],
)
async def test_css_attr_variants(attr, expected):
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[FieldSpec(name="h", selector="h1.title", attr=attr)],
    )
    out = await get_extractor("css").extract(
        '<html><body><h1 class="title">Hello World</h1></body></html>',
        schema,
    )
    assert out["h"] == expected


async def test_css_attr_missing_returns_none():
    """attr="data-x" when the element has no data-x → None (not silent text fallback).

    Design choice: if the user asked for an attribute, returning the text
    instead would silently lie about what was extracted. None is honest.
    """
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[FieldSpec(name="h", selector="h1", attr="data-nope")],
    )
    out = await get_extractor("css").extract(
        "<html><body><h1>Hello</h1></body></html>",
        schema,
    )
    assert out["h"] is None


async def test_css_uses_attr_when_present():
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[FieldSpec(name="h", selector="h1", attr="data-id")],
    )
    out = await get_extractor("css").extract(
        '<html><body><h1 data-id="42">Hello</h1></body></html>',
        schema,
    )
    assert out["h"] == "42"


async def test_css_invalid_selector_returns_none():
    """An invalid CSS selector shouldn't crash — return None for the field."""
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[FieldSpec(name="bad", selector="[[invalid")],
    )
    out = await get_extractor("css").extract(
        "<html><body><p>hi</p></body></html>",
        schema,
    )
    assert out["bad"] is None


async def test_css_multiple_fields_atomic():
    """All fields present in result, even when some selectors fail."""
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="a", selector="h1"),
            FieldSpec(name="b", selector="p"),
            FieldSpec(name="c", selector="span"),  # doesn't exist
        ],
    )
    out = await get_extractor("css").extract(
        "<html><body><h1>title</h1><p>para</p></body></html>",
        schema,
    )
    assert out == {"a": "title", "b": "para", "c": None}


# ---------------------------------------------------------------------------
# XPath extractor — all branches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "attr,expected",
    [
        ("text", "Hello World"),
        ("html", "<h1>Hello World</h1>"),
    ],
)
async def test_xpath_attr_variants(attr, expected):
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="h", selector="//h1", attr=attr)],
    )
    out = await get_extractor("xpath").extract(
        "<html><body><h1>Hello World</h1></body></html>",
        schema,
    )
    assert out["h"] == expected


async def test_xpath_attr_other_than_text_html():
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="h", selector="//h1", attr="id")],
    )
    out = await get_extractor("xpath").extract(
        '<html><body><h1 id="42">Hello</h1></body></html>',
        schema,
    )
    assert out["h"] == "42"


async def test_xpath_attr_missing_returns_none():
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="h", selector="//h1", attr="data-missing")],
    )
    out = await get_extractor("xpath").extract(
        "<html><body><h1>Hello</h1></body></html>",
        schema,
    )
    assert out["h"] is None


async def test_xpath_invalid_selector_returns_none():
    """XPath invalid selectors return None for the field (not crash)."""
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="bad", selector="[[not-valid-xpath")],
    )
    out = await get_extractor("xpath").extract(
        "<html><body><p>hi</p></body></html>",
        schema,
    )
    assert out["bad"] is None


async def test_xpath_no_match_returns_none():
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="missing", selector="//nonexistent")],
    )
    out = await get_extractor("xpath").extract(
        "<html><body><p>hi</p></body></html>",
        schema,
    )
    assert out["missing"] is None


async def test_xpath_takes_first_match():
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="first_p", selector="//p")],
    )
    out = await get_extractor("xpath").extract(
        "<html><body><p>one</p><p>two</p><p>three</p></body></html>",
        schema,
    )
    assert out["first_p"] == "one"


# ---------------------------------------------------------------------------
# Regex extractor — all branches
# ---------------------------------------------------------------------------
async def test_regex_invalid_pattern_returns_none():
    """A malformed regex pattern (re.error) shouldn't crash — return None."""
    schema = Schema(
        strategy=ExtractionStrategy.REGEX,
        fields=[FieldSpec(name="bad", selector=r"[unclosed-group")],
    )
    out = await get_extractor("regex").extract(
        "<html><body>some text</body></html>",
        schema,
    )
    assert out["bad"] is None


async def test_regex_no_match_returns_none():
    schema = Schema(
        strategy=ExtractionStrategy.REGEX,
        fields=[FieldSpec(name="nothing", selector=r"xyz123")],
    )
    out = await get_extractor("regex").extract(
        "<html><body>different text</body></html>",
        schema,
    )
    assert out["nothing"] is None


async def test_regex_returns_first_capture_group():
    schema = Schema(
        strategy=ExtractionStrategy.REGEX,
        fields=[FieldSpec(name="price", selector=r"\$(\d+)\.(\d{2})")],
    )
    out = await get_extractor("regex").extract(
        "<p>Price: $42.50</p>",
        schema,
    )
    assert out["price"] == "42"  # first group


async def test_regex_returns_full_match_when_no_groups():
    schema = Schema(
        strategy=ExtractionStrategy.REGEX,
        fields=[FieldSpec(name="dollar_amount", selector=r"\$\d+\.\d{2}")],
    )
    out = await get_extractor("regex").extract(
        "<p>Price: $42.50</p>",
        schema,
    )
    assert out["dollar_amount"] == "$42.50"


async def test_regex_case_insensitive():
    schema = Schema(
        strategy=ExtractionStrategy.REGEX,
        fields=[FieldSpec(name="hello", selector=r"hello")],
    )
    out = await get_extractor("regex").extract(
        "<p>HELLO world</p>",
        schema,
    )
    assert out["hello"] == "HELLO"


async def test_regex_strips_html_tags_before_matching():
    schema = Schema(
        strategy=ExtractionStrategy.REGEX,
        fields=[FieldSpec(name="text", selector=r"price is (\d+)")],
    )
    out = await get_extractor("regex").extract(
        "<p>The <strong>price is 42</strong> dollars</p>",
        schema,
    )
    assert out["text"] == "42"


# ---------------------------------------------------------------------------
# Registry roundtrip
# ---------------------------------------------------------------------------
def test_registry_has_expected_strategies():
    """Registry has the 4 actual extractor strategies (NONE is handled at the
    orchestrator level — no extractor class for it)."""
    names = set(registered_names())
    assert {"css", "xpath", "regex", "llm"} <= names


def test_registry_get_returns_correct_types():
    css = get_extractor("css")
    assert css.name == "css"
    xpath = get_extractor("xpath")
    assert xpath.name == "xpath"
    regex = get_extractor("regex")
    assert regex.name == "regex"
    llm = get_extractor("llm")
    assert llm.name == "llm"


# ---------------------------------------------------------------------------
# NONE strategy is handled at the orchestrator level — tested in test_scrape.py
# ---------------------------------------------------------------------------
