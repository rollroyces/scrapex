"""Tests for the `scrapex synth` subcommand.

The synth subcommand synthesizes a Schema from a natural-language goal
+ HTML (either fetched from a URL or read from a local file).

Tests cover:
  - Parser accepts valid args
  - Parser rejects missing goal
  - Parser rejects both --synth-url and --html-file
  - HTML file mode reads and synthesizes
  - URL mode fetches and synthesizes (httpx mocked)
  - Output written to file when --synth-output is given
  - LLM errors are surfaced cleanly (exit code 1)
  - Bad arguments give exit code 2
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scrapex.__main__ import (
    _build_synth_parser,
    _synth_main,
    main,
)

SAMPLE_HTML = """
<html>
<body>
    <h1 class="title">Hello World</h1>
    <div class="price">$42.50</div>
</body>
</html>
"""

SYNTH_RESPONSE_JSON = {
    "fields": [
        {
            "name": "title",
            "selector": "h1.title",
            "attr": "text",
            "reason": "page heading",
            "required": False,
        },
        {
            "name": "price",
            "selector": "div.price",
            "attr": "text",
            "reason": "price container",
            "required": False,
        },
    ]
}

# litellm expects the raw string content; we wrap the dict in json.dumps
# The mock simulates the LLM returning JSON that matches the response shape.
SYNTH_LLM_CONTENT = json.dumps(SYNTH_RESPONSE_JSON)


def _patched_litellm(fixed_fields: list[dict]) -> MagicMock:
    """Patch litellm so Schema.from_goal returns the given fields.

    The LLM should return {"fields": [...]}, which we serialize as JSON.
    """
    mock_litellm = MagicMock()
    msg = MagicMock()
    msg.content = json.dumps({"fields": fixed_fields})
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=msg)]
    mock_litellm.completion = MagicMock(return_value=mock_response)
    return mock_litellm


def _patch_schema_synth(mock_litellm: MagicMock):
    """Patch the litellm getter inside scrapex.schema_synth.

    Also patches _resolve_default_model to return a sensible string so
    Schema.from_goal() doesn't bail when no LLM env vars are set.

    Returns a context manager class (use with `as p:`) so it composes
    cleanly with `with` statements.

    Both ``_get_litellm`` and ``_cached_synthesize`` are wrapped with
    ``@lru_cache(maxsize=256)``. ``mock.patch`` replaces ``_get_litellm``
    with a MagicMock, but ``_cached_synthesize`` stays a real cached
    function. If the same (goal, html, model, html_hash) tuple was used
    in a prior test, the prior cached result will be returned here
    without ever calling the patched litellm. So we clear both caches
    before the patch starts and after it exits.
    """
    import scrapex.schema_synth as _ss

    class _CM:
        def __enter__(self):
            _ss._get_litellm.cache_clear()
            _ss._cached_synthesize.cache_clear()
            self._p1 = patch("scrapex.schema_synth._get_litellm", return_value=mock_litellm).__enter__()
            self._p2 = patch(
                "scrapex.schema_synth._resolve_default_model",
                return_value="test-model",
            ).__enter__()
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            self._p2.__exit__(*args)
            self._p1.__exit__(*args)
            _ss._get_litellm.cache_clear()
            _ss._cached_synthesize.cache_clear()

    return _CM()


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_synth_parser_accepts_goal_and_url():
    """Basic parse: `scrapex synth "extract the title" --synth-url <url>`."""
    p = _build_synth_parser()
    args = p.parse_args(["extract the title", "--synth-url", "https://example.com"])
    assert args.goal == "extract the title"
    assert args.synth_url == "https://example.com"
    assert args.html_file is None
    assert args.synth_output is None
    assert args.synth_model is None


def test_synth_parser_accepts_html_file():
    """`scrapex synth "extract..." --html-file /tmp/x.html` parses cleanly."""
    p = _build_synth_parser()
    args = p.parse_args(["extract", "--html-file", "/tmp/x.html"])
    assert args.html_file == "/tmp/x.html"
    assert args.synth_url is None


def test_synth_parser_accepts_short_output_flag():
    """`-o` is the short form of `--synth-output`."""
    p = _build_synth_parser()
    args = p.parse_args(["extract", "--synth-url", "https://example.com", "-o", "schema.json"])
    assert args.synth_output == "schema.json"


def test_synth_parser_requires_goal():
    """Missing goal: argparse error."""
    p = _build_synth_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--synth-url", "https://example.com"])


# ---------------------------------------------------------------------------
# Dispatch test
# ---------------------------------------------------------------------------


def test_synth_keyword_dispatches_to_synth_main(tmp_path):
    """When argv[0] is 'synth', main() routes to _synth_main."""
    html_file = tmp_path / "page.html"
    html_file.write_text(SAMPLE_HTML, encoding="utf-8")

    mock_litellm = _patched_litellm(SYNTH_RESPONSE_JSON["fields"])

    with _patch_schema_synth(mock_litellm):
        rc = main(["synth", "extract title and price", "--html-file", str(html_file)])

    assert rc == 0


def test_synth_keyword_does_not_trigger_on_scrape_url():
    """A URL starting with 'synth' as a path still goes to scrape mode.

    Real URLs always start with a scheme (http/https/ftp). A bare 'synth'
    arg is the only thing that triggers the subcommand.
    """
    p = _build_synth_parser()
    args = p.parse_args(["extract title", "--synth-url", "https://synth.example.com"])
    assert args.synth_url == "https://synth.example.com"


# ---------------------------------------------------------------------------
# HTML file mode
# ---------------------------------------------------------------------------


def test_synth_with_html_file_outputs_to_stdout(tmp_path, capsys):
    """--html-file mode reads the file, calls from_goal, prints JSON to stdout."""
    html_file = tmp_path / "page.html"
    html_file.write_text(SAMPLE_HTML, encoding="utf-8")

    mock_litellm = _patched_litellm(SYNTH_RESPONSE_JSON["fields"])

    with _patch_schema_synth(mock_litellm):
        rc = _synth_main(["extract title", "--html-file", str(html_file)])

    captured = capsys.readouterr()
    assert rc == 0
    # Output is a JSON Schema dump
    assert '"fields"' in captured.out
    assert '"title"' in captured.out
    assert '"price"' in captured.out


def test_synth_with_html_file_writes_to_output(tmp_path):
    """When --synth-output is set, schema is written there instead of stdout."""
    html_file = tmp_path / "page.html"
    html_file.write_text(SAMPLE_HTML, encoding="utf-8")
    out_file = tmp_path / "schema.json"

    mock_litellm = _patched_litellm(SYNTH_RESPONSE_JSON["fields"])

    with _patch_schema_synth(mock_litellm):
        rc = _synth_main(
            ["extract", "--html-file", str(html_file), "-o", str(out_file)]
        )

    assert rc == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "fields" in data
    assert len(data["fields"]) == 2


def test_synth_with_html_file_missing(tmp_path):
    """A non-existent HTML file gives exit code 1."""
    missing = tmp_path / "does-not-exist.html"
    rc = _synth_main(["extract", "--html-file", str(missing)])
    assert rc == 1


# ---------------------------------------------------------------------------
# URL mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synth_with_url_fetches_html():
    """--synth-url mode fetches the URL via httpx, then synthesizes."""
    import respx
    from httpx import Response

    mock_litellm = _patched_litellm(SYNTH_RESPONSE_JSON["fields"])

    with _patch_schema_synth(mock_litellm), respx.mock(base_url="https://example.com") as r:
        r.get("/").mock(return_value=Response(200, text=SAMPLE_HTML))
        args = _build_synth_parser().parse_args(
            ["extract", "--synth-url", "https://example.com/"]
        )
        from scrapex.__main__ import _synth_async
        rc = await _synth_async(args)

    assert rc == 0


def test_synth_with_url_fetch_error():
    """Network errors give exit code 1."""
    import respx
    from httpx import Response

    # 500 server error raises on raise_for_status
    with respx.mock(base_url="https://example.com") as r:
        r.get("/").mock(return_value=Response(500, text="server error"))
        rc = _synth_main(["extract", "--synth-url", "https://example.com/"])
        assert rc == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_synth_rejects_both_url_and_html_file(tmp_path):
    """Both --synth-url and --html-file together → exit code 2."""
    rc = _synth_main([
        "extract",
        "--synth-url", "https://example.com",
        "--html-file", str(tmp_path / "x.html"),
    ])
    assert rc == 2


def test_synth_rejects_neither_url_nor_html_file():
    """Neither --synth-url nor --html-file → exit code 2."""
    rc = _synth_main(["extract"])
    assert rc == 2


# ---------------------------------------------------------------------------
# LLM error handling
# ---------------------------------------------------------------------------


def test_synth_surfaces_llm_error(tmp_path):
    """If Schema.from_goal raises, exit code 1 with an error message."""
    html_file = tmp_path / "page.html"
    html_file.write_text(SAMPLE_HTML, encoding="utf-8")

    # Build a litellm mock whose .completion raises.
    broken_litellm = MagicMock()
    broken_litellm.completion = MagicMock(side_effect=RuntimeError("LLM down"))

    with _patch_schema_synth(broken_litellm):
        rc = _synth_main(["extract", "--html-file", str(html_file)])

    assert rc == 1
