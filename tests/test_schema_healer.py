"""Tests for Schema.heal() — single-shot LLM-driven schema auto-patching."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scrapex import Schema
from scrapex.errors import ConfigurationError
from scrapex.schema_healer import _heal_schema


def _fake_litellm_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def broken_schema():
    """A schema whose selectors no longer match (simulating redesign)."""
    return Schema(
        strategy=__import__("scrapex").ExtractionStrategy.CSS,
        fields=[
            __import__("scrapex").FieldSpec(
                name="title",
                selector="h1.old-title-class",
                description="originally targeted h1.old-title-class",
            ),
            __import__("scrapex").FieldSpec(
                name="price",
                selector="span.price-old",
                attr="text",
            ),
            __import__("scrapex").FieldSpec(
                name="download",
                selector="a.download-old",
                attr="href",
            ),
        ],
    )


# --- Happy path ----------------------------------------------------------


def test_heal_patches_selectors_from_llm(broken_schema):
    """LLM returns new selectors; the new schema uses them."""
    response = json.dumps(
        {
            "fixes": [
                {
                    "name": "title",
                    "selector": "h1.new-title-class",
                    "reason": "page redesign changed the class",
                },
                {
                    "name": "price",
                    "selector": "div.price-new",
                    "reason": "now wrapped in a div",
                },
                # download is omitted by the LLM (not confident)
            ]
        }
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        new = _heal_schema(broken_schema, "<html>...</html>", llm_model="test-model")
    # 2 fields patched, 1 kept original
    by_name = {f.name: f for f in new.fields}
    assert by_name["title"].selector == "h1.new-title-class"
    assert by_name["price"].selector == "div.price-new"
    assert by_name["download"].selector == "a.download-old"  # unchanged
    # reason propagated to patched fields
    assert "healed:" in by_name["title"].description
    assert "page redesign" in by_name["title"].description


def test_heal_does_not_mutate_original(broken_schema):
    """The original schema must be untouched (deep copy semantics)."""
    response = json.dumps(
        {"fixes": [{"name": "title", "selector": "h1.new", "reason": "fixed"}]}
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        _heal_schema(broken_schema, "<html/>", llm_model="test")
    # Original is untouched
    title_field = broken_schema.fields[0]
    assert title_field.selector == "h1.old-title-class"
    assert "originally targeted" in (title_field.description or "")


def test_heal_preserves_attr(broken_schema):
    """FieldSpec.attr is preserved through the heal (text vs href)."""
    response = json.dumps(
        {"fixes": [{"name": "download", "selector": "a.new-download", "reason": ""}]}
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        new = _heal_schema(broken_schema, "<html/>", llm_model="test")
    download = next(f for f in new.fields if f.name == "download")
    assert download.attr == "href"  # preserved from original


# --- Empty / edge cases --------------------------------------------------


def test_heal_empty_schema_returns_copy():
    """A schema with no fields just returns a copy."""
    empty = Schema(
        strategy=__import__("scrapex").ExtractionStrategy.CSS, fields=[]
    )
    # Should not even hit the LLM
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        new = _heal_schema(empty, "<html/>", llm_model="test")
    assert len(new.fields) == 0
    mock_get.assert_not_called()


def test_heal_with_no_fixes_returns_unchanged_copy(broken_schema):
    """LLM returns empty fixes list → all fields unchanged."""
    response = json.dumps({"fixes": []})
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        new = _heal_schema(broken_schema, "<html/>", llm_model="test")
    for orig, patched in zip(broken_schema.fields, new.fields, strict=True):
        assert orig.selector == patched.selector


def test_heal_skips_malformed_fixes(broken_schema):
    """Entries without name or selector are dropped (not crashing)."""
    response = json.dumps(
        {
            "fixes": [
                {"name": 123, "selector": "h1.x"},  # name not str
                {"name": "price"},  # no selector
                {"name": "title", "selector": ""},  # empty selector
                {"name": "title", "selector": "h1.real"},  # good
            ]
        }
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        new = _heal_schema(broken_schema, "<html/>", llm_model="test")
    title = next(f for f in new.fields if f.name == "title")
    assert title.selector == "h1.real"


# --- Error paths ---------------------------------------------------------


def test_heal_handles_litellm_exception(broken_schema):
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(side_effect=ConnectionError("net"))
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="failed to call"):
            _heal_schema(broken_schema, "<html/>", llm_model="test")


def test_heal_handles_non_json(broken_schema):
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response("not json at all")
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="non-JSON"):
            _heal_schema(broken_schema, "<html/>", llm_model="test")


def test_heal_handles_empty_response(broken_schema):
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response("")
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="empty response"):
            _heal_schema(broken_schema, "<html/>", llm_model="test")


def test_heal_handles_missing_fixes_key(broken_schema):
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response('{"foo": "bar"}')
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="missing 'fixes'"):
            _heal_schema(broken_schema, "<html/>", llm_model="test")


def test_heal_handles_fixes_not_a_list(broken_schema):
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response('{"fixes": "should be a list"}')
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="not a list"):
            _heal_schema(broken_schema, "<html/>", llm_model="test")


# --- Prompt content ------------------------------------------------------


def test_heal_includes_field_names_in_prompt(broken_schema):
    """Field names must appear in the prompt sent to the LLM."""
    captured = {}
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()

        def capture(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            return _fake_litellm_response('{"fixes": []}')

        mock_litellm.completion = MagicMock(side_effect=capture)
        mock_get.return_value = mock_litellm
        _heal_schema(broken_schema, "<html><body><p>x</p></body></html>", llm_model="test")

    prompt = captured["prompt"]
    # The field names are sent to the LLM as JSON
    assert "title" in prompt
    assert "price" in prompt
    assert "download" in prompt
    # The HTML body content is preserved by the cleaner
    assert "<p>x</p>" in prompt


# --- Integration via the Schema.heal() method -----------------------------


def test_schema_heal_method_attached():
    """Schema.heal is attached at import time."""
    from scrapex import Schema

    assert callable(getattr(Schema, "heal", None))


def test_schema_heal_method_calls_internal_function(broken_schema):
    """Schema.heal() delegates to _heal_schema."""
    response = json.dumps(
        {"fixes": [{"name": "title", "selector": "h1.x", "reason": ""}]}
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        new = broken_schema.heal("<html/>", llm_model="test")
    title = next(f for f in new.fields if f.name == "title")
    assert title.selector == "h1.x"
