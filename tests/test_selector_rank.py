"""Tests for selector_rank — speculative feature, no real LLM in CI."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scrapex.errors import ConfigurationError
from scrapex.selector_rank import _rank_selectors


def _fake_litellm_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# --- Happy path ----------------------------------------------------------


def test_rank_selectors_returns_top_k():
    """The LLM returns a list of selectors with scores; we return top K."""
    response = (
        '{"selectors": ['
        '{"selector": "a.register", "score": 0.95, "reason": "matches the keyword register"},'
        '{"selector": "a.download", "score": 0.7, "reason": "download link"},'
        '{"selector": "a.view", "score": 0.3, "reason": "view link"}'
        ']}'
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>...</html>", "the register link", top_k=2)
    assert len(result) == 2
    assert result[0]["selector"] == "a.register"
    assert result[0]["score"] == 0.95
    assert result[1]["selector"] == "a.download"


def test_rank_selectors_sorts_by_score_desc():
    """Out-of-order input gets sorted by score descending."""
    response = (
        '{"selectors": ['
        '{"selector": "a.low", "score": 0.2},'
        '{"selector": "a.high", "score": 0.9},'
        '{"selector": "a.mid", "score": 0.5}'
        ']}'
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x")
    scores = [r["score"] for r in result]
    assert scores == sorted(scores, reverse=True)


# --- Edge cases ----------------------------------------------------------


def test_rank_selectors_handles_empty_list():
    response = '{"selectors": []}'
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x")
    assert result == []


def test_rank_selectors_skips_malformed_entries():
    """Non-dict entries and entries with no selector are dropped."""
    response = (
        '{"selectors": ['
        '42,'  # not a dict
        '{"selector": "a.ok"},'  # good
        '{"score": 0.9},'  # missing selector
        '{"selector": ""}'  # empty selector
        ']}'
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x")
    assert len(result) == 1
    assert result[0]["selector"] == "a.ok"


def test_rank_selectors_handles_missing_score():
    """Missing score defaults to 0.0 (not an exception)."""
    response = '{"selectors": [{"selector": "a.x"}]}'
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x")
    assert result[0]["score"] == 0.0


def test_rank_selectors_caps_at_top_k():
    """If LLM returns 10 selectors and top_k=3, we return only 3."""
    response = (
        '{"selectors": ['
        + ",".join(
            f'{{"selector": "a{i}", "score": {1.0 - i*0.1}}}'
            for i in range(10)
        )
        + "]}"
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x", top_k=3)
    assert len(result) == 3
    assert result[0]["selector"] == "a0"
    assert result[1]["selector"] == "a1"
    assert result[2]["selector"] == "a2"


def test_rank_selectors_default_top_k_is_3():
    """If top_k is not passed, default is 3."""
    response = (
        '{"selectors": ['
        + ",".join(f'{{"selector": "a{i}", "score": {1.0 - i*0.1}}}' for i in range(5))
        + "]}"
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x")  # no top_k
    assert len(result) == 3


# --- Error paths ---------------------------------------------------------


def test_rank_selectors_handles_litellm_exception():
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            side_effect=ConnectionError("network down")
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="failed to call"):
            _rank_selectors("<html>x</html>", "x")


def test_rank_selectors_handles_non_json():
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response("not json")
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="non-JSON"):
            _rank_selectors("<html>x</html>", "x")


def test_rank_selectors_handles_missing_selectors_key():
    response = '{"foo": "bar"}'
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="missing 'selectors'"):
            _rank_selectors("<html>x</html>", "x")


def test_rank_selectors_handles_selectors_not_a_list():
    response = '{"selectors": "should be a list"}'
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError, match="not a list"):
            _rank_selectors("<html>x</html>", "x")


def test_rank_selectors_handles_empty_response():
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response("")
        )
        mock_get.return_value = mock_litellm
        with pytest.raises(ConfigurationError):
            _rank_selectors("<html>x</html>", "x")


# --- Prompt content ------------------------------------------------------


def test_rank_selectors_includes_hint_and_html_in_prompt():
    """The hint and HTML must appear in the prompt sent to the LLM."""
    captured = {}

    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()

        def capture(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            return _fake_litellm_response('{"selectors": []}')

        mock_litellm.completion = MagicMock(side_effect=capture)
        mock_get.return_value = mock_litellm
        _rank_selectors("<p class='special'>hi</p>", "the special paragraph")

    assert "special paragraph" in captured["prompt"]
    # HTML should be cleaned (script/style stripped, etc.). The 'special'
    # class survives the clean.
    assert "special" in captured["prompt"]


def test_rank_selectors_passes_top_k_in_prompt():
    """top_k value must be in the prompt so the LLM knows how many to return."""
    captured = {}
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()

        def capture(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            return _fake_litellm_response('{"selectors": []}')

        mock_litellm.completion = MagicMock(side_effect=capture)
        mock_get.return_value = mock_litellm
        _rank_selectors("<html>x</html>", "x", top_k=7)

    assert "7" in captured["prompt"]


# --- Sanity check: scoring tie-break is stable ----------------------------


def test_rank_selectors_stable_order_for_ties():
    """Two selectors with equal scores preserve their input order."""
    response = (
        '{"selectors": ['
        '{"selector": "a.first", "score": 0.5},'
        '{"selector": "a.second", "score": 0.5}'
        ']}'
    )
    with patch("scrapex.schema_synth._get_litellm") as mock_get:
        mock_litellm = MagicMock()
        mock_litellm.completion = MagicMock(
            return_value=_fake_litellm_response(response)
        )
        mock_get.return_value = mock_litellm
        result = _rank_selectors("<html>x</html>", "x")
    assert result[0]["selector"] == "a.first"
    assert result[1]["selector"] == "a.second"
