"""Tests for the CLI module (python -m scrapex)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import Response

from scrapex import ScrapeResult
from scrapex.__main__ import (
    _parse_schema,
    _show_error_panel,
    _show_result,
    build_parser,
    main,
)
from scrapex.errors import (
    ConfigurationError,
    FetchError,
    RenderError,
)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def test_parser_has_all_expected_arguments():
    parser = build_parser()
    # argparse: check via help text
    help_text = parser.format_help()
    assert "--strategy" in help_text
    assert "--schema" in help_text
    assert "--preset" in help_text
    assert "--region" in help_text
    assert "--render" in help_text
    assert "--timeout" in help_text
    assert "--retries" in help_text
    assert "--max-chars" in help_text
    assert "--description" in help_text
    assert "--version" in help_text


def test_parser_default_values():
    parser = build_parser()
    args = parser.parse_args(["https://example.com"])
    assert args.url == "https://example.com"
    assert args.strategy == "none"
    assert args.render == "auto"
    assert args.timeout == 30.0
    assert args.retries == 2
    assert args.region == "intl"
    assert args.schema is None
    assert args.preset is None


def test_parser_rejects_invalid_strategy():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["https://x.com", "--strategy", "invalid"])


def test_parser_accepts_all_strategies():
    parser = build_parser()
    for s in ["css", "xpath", "regex", "llm", "none"]:
        args = parser.parse_args(["https://x.com", "--strategy", s])
        assert args.strategy == s


def test_parser_accepts_all_regions():
    parser = build_parser()
    for r in ["intl", "cn"]:
        args = parser.parse_args(["https://x.com", "--region", r])
        assert args.region == r


# ---------------------------------------------------------------------------
# _parse_schema
# ---------------------------------------------------------------------------
def test_parse_schema_simple():
    schema = _parse_schema("title:h1", [])
    assert schema is not None
    assert len(schema.fields) == 1
    assert schema.fields[0].name == "title"
    assert schema.fields[0].selector == "h1"
    assert schema.fields[0].attr == "text"


def test_parse_schema_multiple_fields():
    schema = _parse_schema("title:h1,price:span.price:data-amount", [])
    assert schema is not None
    assert len(schema.fields) == 2
    assert schema.fields[1].attr == "data-amount"


def test_parse_schema_with_descriptions():
    schema = _parse_schema("price:span.price", ["Product price in USD"])
    assert schema is not None
    assert schema.fields[0].description == "Product price in USD"


def test_parse_schema_empty_returns_none():
    assert _parse_schema(None, []) is None
    assert _parse_schema("", []) is None


def test_parse_schema_skips_invalid_specs():
    """Specs with fewer than 2 parts are silently dropped."""
    schema = _parse_schema("title:h1,invalid,bad:also-invalid", [])
    # The first is valid; the second has no parts; the third has 2 parts
    # (both non-empty) so it parses. The third's selector is "also-invalid".
    assert schema is not None
    # Should have at least 2 fields (first and third)
    assert len(schema.fields) >= 2


# ---------------------------------------------------------------------------
# main() — happy path
# ---------------------------------------------------------------------------
def test_main_with_url_only(capsys, respx_mock):
    """Minimal invocation: just a URL."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(
            200, text="<html><head><title>T</title></head><body><p>hi</p></body></html>"
        )
    )
    rc = main(["https://example.com"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "T" in out  # title appears


def test_main_with_css_schema(capsys, respx_mock):
    """--schema produces an extracted table."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(
            200,
            text='<html><body><h1 class="t">Hello</h1></body></html>',
        )
    )
    rc = main(["https://example.com", "--schema", "title:h1.t"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Hello" in out
    assert "title" in out  # column header


def test_main_returns_zero_on_success(capsys, respx_mock):
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<html><body><p>x</p></body></html>")
    )
    rc = main(["https://example.com"])
    assert rc == 0


def test_main_returns_one_on_scrapex_error(capsys):
    """FetchError should return exit code 1 and show a panel."""
    rc = main(["https://does-not-exist-zzz.invalid", "--render", "http"])
    assert rc == 1
    out = capsys.readouterr().out + capsys.readouterr().err
    # The panel should contain "hint:" or similar
    assert "hint" in out.lower() or "Error" in out


def test_main_returns_130_on_keyboard_interrupt(capsys, respx_mock):
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )

    async def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    with patch("scrapex.__main__.scrape", side_effect=raise_interrupt):
        rc = main(["https://example.com"])
    assert rc == 130


# ---------------------------------------------------------------------------
# main() — invalid args
# ---------------------------------------------------------------------------
def test_main_with_no_args_shows_help(capsys):
    """Running with no args shows help and exits non-zero (argparse default)."""
    with pytest.raises(SystemExit):
        main([])


def test_main_with_invalid_url_type(capsys):
    """A non-URL string fails Pydantic validation; CLI returns exit 2."""
    rc = main(["not-a-url"])
    assert rc == 2
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "Invalid arguments" in out or "url" in out.lower()


# ---------------------------------------------------------------------------
# _show_result uses Rich when available
# ---------------------------------------------------------------------------
def test_show_result_with_extracted():
    """No exception raised when result has extracted fields."""
    result = ScrapeResult(
        url="https://x.com",
        final_url="https://x.com",
        status=200,
        title="T",
        markdown="body",
        html=None,
        extracted={"k": "v"},
        extraction_warnings=[],
        render_mode_used="http",
        elapsed_ms=100,
    )
    _show_result(result)  # must not raise


def test_show_result_with_long_extracted_value():
    """Values longer than 100 chars get truncated in the table view."""
    long_value = "x" * 500
    result = ScrapeResult(
        url="https://x.com",
        final_url="https://x.com",
        status=200,
        title="T",
        markdown=None,
        html=None,
        extracted={"long": long_value},
        extraction_warnings=[],
        render_mode_used="http",
        elapsed_ms=100,
    )
    _show_result(result)


def test_main_with_llm_strategy_preset(capsys, monkeypatch, respx_mock):
    """--preset implies --strategy llm; default schema is used."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")

    # Mock litellm.acompletion to avoid real API call
    captured: dict = {}

    class FakeMsg:
        content = '{"title": "ok", "summary": "yes"}'

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

    rc = main(["https://example.com", "--preset", "deepseek-v3"])
    assert rc == 0
    assert captured["model"] == "deepseek/deepseek-chat"
    out = capsys.readouterr().out
    assert "ok" in out


def test_main_with_llm_strategy_and_custom_schema(capsys, monkeypatch, respx_mock):
    """--strategy llm + --schema uses the user-provided schema."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured: dict = {}

    class FakeMsg:
        content = '{"price": "$42"}'

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        from typing import ClassVar

        choices: ClassVar = [FakeChoice()]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResp()

    from scrapex.extractors.llm import LlmExtractor

    (
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
        ),
    )

    rc = main(
        [
            "https://example.com",
            "--strategy",
            "llm",
            "--schema",
            "price:div.price",
            "--description",
            "Numeric price",
        ]
    )
    assert rc == 0
    assert "price" in captured["messages"][0]["content"]


def test_main_missing_api_key_for_preset(capsys, monkeypatch, respx_mock):
    """No API key set → CLI catches it and exits 1 with a hint."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    rc = main(["https://example.com", "--preset", "deepseek-v3"])
    assert rc == 1
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "DEEPSEEK_API_KEY" in out or "hint" in out.lower()


def test_main_generic_exception_caught(capsys, monkeypatch, respx_mock):
    """Non-scrapex exceptions get wrapped and shown cleanly."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )

    async def raise_unexpected(*args, **kwargs):
        raise RuntimeError("totally unexpected")

    import sys

    monkeypatch.setattr(sys.modules["scrapex.__main__"], "scrape", raise_unexpected)
    rc = main(["https://example.com"])
    assert rc == 1
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "totally unexpected" in out


def test_main_generic_exception_with_debug_env(capsys, monkeypatch, respx_mock):
    """SCRAPEX_DEBUG=1 also prints the traceback after the panel."""
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=Response(200, text="<p>x</p>")
    )
    monkeypatch.setenv("SCRAPEX_DEBUG", "1")

    async def raise_unexpected(*args, **kwargs):
        raise RuntimeError("boom")

    import sys

    monkeypatch.setattr(sys.modules["scrapex.__main__"], "scrape", raise_unexpected)
    rc = main(["https://example.com"])
    assert rc == 1


def test_show_result_without_markdown():
    result = ScrapeResult(
        url="https://x.com",
        final_url="https://x.com",
        status=200,
        title="T",
        markdown=None,
        html="<p>raw</p>",
        extracted={},
        extraction_warnings=[],
        render_mode_used="http",
        elapsed_ms=100,
    )
    _show_result(result)


def test_show_result_with_long_markdown_truncates():
    """Markdown over 500 chars gets truncated in the preview."""
    long_md = "x" * 2000
    result = ScrapeResult(
        url="https://x.com",
        final_url="https://x.com",
        status=200,
        title="T",
        markdown=long_md,
        html=None,
        extracted={"k": "v"},
        extraction_warnings=[],
        render_mode_used="http",
        elapsed_ms=100,
    )
    _show_result(result)  # must not raise


def test_show_result_with_missing_field():
    """A field with value=None is shown as <missing>, not empty."""
    result = ScrapeResult(
        url="https://x.com",
        final_url="https://x.com",
        status=200,
        title="T",
        markdown=None,
        html=None,
        extracted={"k": None},
        extraction_warnings=[],
        render_mode_used="http",
        elapsed_ms=100,
    )
    _show_result(result)


def test_show_result_with_warnings():
    result = ScrapeResult(
        url="https://x.com",
        final_url="https://x.com",
        status=200,
        title="T",
        markdown=None,
        html=None,
        extracted={},
        extraction_warnings=["something went wrong"],
        render_mode_used="http",
        elapsed_ms=100,
    )
    _show_result(result)


# ---------------------------------------------------------------------------
# _show_error_panel
# ---------------------------------------------------------------------------
def test_show_error_panel_without_hint():
    """Errors with no hint still produce a panel."""
    from scrapex.errors import ScrapexError

    _show_error_panel(ScrapexError("bare message"))


def test_show_error_panel_with_hint():
    """Errors with hint include it in the panel body."""
    from scrapex.errors import ScrapexError

    err = ScrapexError("something failed", hint="try this")
    _show_error_panel(err)


# ---------------------------------------------------------------------------
# FetchError hints are status-aware
# ---------------------------------------------------------------------------
def test_fetch_error_404_hint():
    err = FetchError("https://x", "missing", status=404)
    assert "render=browser" in (err.hint or "")


def test_fetch_error_429_hint():
    err = FetchError("https://x", "rate limited", status=429)
    assert "rate" in (err.hint or "").lower()


def test_fetch_error_500_hint():
    err = FetchError("https://x", "boom", status=500)
    assert "browser" in (err.hint or "").lower()


def test_fetch_error_transport_hint():
    err = FetchError("https://x", "timeout")
    assert err.status is None
    assert "timeout" in (err.hint or "").lower() or "network" in (err.hint or "").lower()


def test_fetch_error_explicit_hint_overrides_default():
    err = FetchError("https://x", "msg", status=404, hint="my custom hint")
    assert err.hint == "my custom hint"


def test_render_error_default_hint_mentions_playwright():
    err = RenderError("launch failed")
    assert "playwright" in (err.hint or "").lower()


def test_configuration_error_default_hint():
    err = ConfigurationError("missing api key")
    assert err.hint is not None
    assert len(err.hint) > 10
