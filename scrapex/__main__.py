"""Command-line interface for scrapex.

Try it with::

    python -m scrapex https://example.com
    python -m scrapex https://news.example.com --strategy llm --preset deepseek-v3

No Python required to use it — just an ``import scrapex`` install.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from scrapex import (
    ExtractionStrategy,
    FieldSpec,
    RenderMode,
    Schema,
    ScrapeRequest,
    ScrapeResult,
    __version__,
    china,
    scrape,
)
from scrapex.errors import ScrapexError

# Detect Rich ONCE at module load so the rest of the file can rely on it.
try:
    from rich.console import Console as RichConsole
    from rich.panel import Panel as RichPanel
    from rich.table import Table as RichTable

    _HAS_RICH = True
except ImportError:  # pragma: no cover
    RichConsole = None  # type: ignore[assignment,misc]
    RichPanel = None  # type: ignore[assignment,misc]
    RichTable = None  # type: ignore[assignment,misc]
    _HAS_RICH = False


# ---------------------------------------------------------------------------
# Output helpers — Rich when available, plain text fallback
# ---------------------------------------------------------------------------
_console: Any
if _HAS_RICH:
    _console = RichConsole()
else:

    class _FallbackConsole:
        def print(self, *args: Any, **kwargs: Any) -> None:
            print(*args)

    _console = _FallbackConsole()


def _err(msg: str) -> None:
    """Print to stderr in red when Rich is available."""
    if _HAS_RICH:
        _console.print(f"[bold red]{msg}[/bold red]", style="red")
    else:
        print(msg, file=sys.stderr)


def _info(msg: str) -> None:
    if _HAS_RICH:
        _console.print(f"[dim]{msg}[/dim]")
    else:
        print(f"# {msg}")


def _show_error_panel(err: ScrapexError) -> None:
    """Render an error with its hint in a visually distinct way."""
    if _HAS_RICH:
        body = str(err)
        if err.hint:
            body += f"\n\n[yellow]hint:[/yellow] {err.hint}"
        _console.print(RichPanel(body, title="[bold red]Error[/bold red]", border_style="red"))
    else:
        _err(str(err))
        if err.hint:
            _info(f"hint: {err.hint}")


def _show_result(result: ScrapeResult) -> None:
    """Render a ScrapeResult in a human-friendly layout."""
    if _HAS_RICH:
        # Header panel with status + timings
        header = (
            f"[bold]URL:[/bold]      {result.url}\n"
            f"[bold]Final URL:[/bold] {result.final_url or result.url}\n"
            f"[bold]Status:[/bold]   {result.status}\n"
            f"[bold]Mode:[/bold]     {result.render_mode_used or 'unknown'}\n"
            f"[bold]Elapsed:[/bold]  {result.elapsed_ms}ms"
        )
        if result.title:
            header += f"\n[bold]Title:[/bold]    {result.title}"
        _console.print(RichPanel(header, title="scrape result", border_style="cyan"))

        # Extracted fields
        if result.extracted:
            table = RichTable(title="Extracted", show_header=True, header_style="bold cyan")
            table.add_column("Field", style="cyan", no_wrap=True)
            table.add_column("Value")
            for k, v in result.extracted.items():
                val_str = str(v) if v is not None else "[dim]<missing>[/dim]"
                if len(val_str) > 100:
                    val_str = val_str[:97] + "..."
                table.add_row(k, val_str)
            _console.print(table)
        else:
            _info("No fields extracted (use --strategy llm or provide a --schema)")

        # Warnings
        if result.extraction_warnings:
            for w in result.extraction_warnings:
                _console.print(f"  [yellow]![/yellow] {w}")

        # Markdown preview
        if result.markdown:
            preview = result.markdown[:500]
            if len(result.markdown) > 500:
                preview += "\n[dim]…(truncated)[/dim]"
            _console.print(RichPanel(preview, title="Markdown preview", border_style="dim"))
    else:
        # Plain-text fallback
        print("=" * 60)
        print(f"URL:        {result.url}")
        print(f"Final URL:  {result.final_url or result.url}")
        print(f"Status:     {result.status}")
        print(f"Mode:       {result.render_mode_used or 'unknown'}")
        print(f"Elapsed:    {result.elapsed_ms}ms")
        if result.title:
            print(f"Title:      {result.title}")
        print("=" * 60)
        if result.extracted:
            print("Extracted:")
            for k, v in result.extracted.items():
                vstr = str(v) if v is not None else "<missing>"
                print(f"  {k}: {vstr[:80]}")
        if result.extraction_warnings:
            for w in result.extraction_warnings:
                print(f"  ! {w}")
        if result.markdown:
            print("-" * 60)
            print(result.markdown[:500])
            if len(result.markdown) > 500:
                print("…(truncated)")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser.

    Returned parser exposes the same flags documented in the README's
    CLI section. Lives in its own function so tests can introspect it
    without invoking the full ``main()`` flow.

    The CLI supports two modes:
      - Default scrape mode: `scrapex <url> [flags]`
      - Synth mode: `scrapex synth <goal> --url <url> [flags]`
    Detection happens in ``main()`` based on the first positional arg.
    """
    p = argparse.ArgumentParser(
        prog="scrapex",
        description="Scrape a URL with AI-friendly output. "
        "Try: python -m scrapex https://example.com",
    )
    p.add_argument("url", help="URL to scrape")
    p.add_argument(
        "--strategy",
        "-s",
        choices=["css", "xpath", "regex", "llm", "none"],
        default="none",
        help="Extraction strategy (default: none — just markdown)",
    )
    p.add_argument(
        "--schema",
        "-S",
        help="Comma-separated fields as name:selector[:attr] pairs, e.g. "
        "'title:h1,price:span.price:data-amount'",
    )
    p.add_argument(
        "--preset",
        "-p",
        choices=[p.name for p in china.presets()],
        help="China LLM preset (implies --strategy llm). e.g. deepseek-v3",
    )
    p.add_argument(
        "--region",
        "-r",
        choices=["intl", "cn"],
        default="intl",
        help="API region for China LLM presets (default: intl)",
    )
    p.add_argument(
        "--render",
        choices=["http", "browser", "auto"],
        default="auto",
        help="Fetch strategy (default: auto — HTTP first, browser fallback)",
    )
    p.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=30.0,
        help="Timeout in seconds (default: 30)",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Max retries on transient errors (default: 2)",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Max characters in markdown output",
    )
    p.add_argument(
        "--description",
        "-d",
        action="append",
        default=[],
        help="Field description (LLM strategy). Repeatable. Use after --schema.",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"scrapex {__version__}",
    )
    return p


# ---------------------------------------------------------------------------
# Schema construction helpers
# ---------------------------------------------------------------------------
def _parse_schema(
    arg: str | None, descriptions: list[str], strategy: ExtractionStrategy = ExtractionStrategy.CSS
) -> Schema | None:
    """Parse 'title:h1,price:span.price:data-amount' into a Schema.

    Honors the user's ``strategy`` choice — if they asked for LLM but also
    passed --schema, the resulting Schema must use LLM (the schema's
    strategy overrides the per-field behavior, not vice versa).
    """
    if not arg:
        return None
    fields = []
    for spec in arg.split(","):
        parts = spec.strip().split(":")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        selector = parts[1].strip()
        attr = parts[2].strip() if len(parts) > 2 else "text"
        description = None
        if descriptions:
            description = descriptions.pop(0)
        fields.append(FieldSpec(name=name, selector=selector, attr=attr, description=description))
    if not fields:
        return None
    return Schema(strategy=strategy, fields=fields)


# ---------------------------------------------------------------------------
# Synth subcommand — synthesize a Schema from a goal + HTML
# ---------------------------------------------------------------------------


def _build_synth_parser() -> argparse.ArgumentParser:
    """Build a parser for the `synth` subcommand.

    Usage:
        scrapex synth <goal> --synth-url <url> [--html-file ...] [-o ...]

    Args:
        goal: Natural-language goal string (positional, required).
        --synth-url: URL to fetch HTML from.
        --html-file: Local HTML file (alternative to --synth-url).
        --synth-output, -o: Where to write the JSON schema (default stdout).
        --synth-model: LLM model string.

    Exit codes match the main CLI:
        0 — success
        1 — LLM call failed
        2 — bad arguments
    """
    p = argparse.ArgumentParser(
        prog="scrapex synth",
        description="Synthesize a Schema from a natural-language goal + HTML.",
    )
    p.add_argument("goal", help="Natural-language goal. Example: 'Extract the product title and price'")
    p.add_argument(
        "--synth-url",
        help="URL to fetch HTML from (mutually exclusive with --html-file)",
    )
    p.add_argument(
        "--html-file",
        help="Path to a local HTML file (mutually exclusive with --synth-url)",
    )
    p.add_argument(
        "--synth-output",
        "-o",
        default=None,
        help="Where to write the synthesized schema (JSON). Default: stdout.",
    )
    p.add_argument(
        "--synth-model",
        default=None,
        help="LLM model string (e.g. 'gpt-4o-mini'). Default: heuristic resolution.",
    )
    return p


async def _synth_async(args: argparse.Namespace) -> int:
    """Run the synth subcommand. Returns process exit code."""
    # Validate mutually exclusive options
    if bool(args.synth_url) == bool(args.html_file):
        _err("Specify exactly one of --synth-url or --html-file")
        return 2

    # Get the HTML
    if args.html_file:
        try:
            html = Path(args.html_file).read_text(encoding="utf-8")
        except OSError as e:
            _err(f"Cannot read {args.html_file}: {e}")
            return 1
    else:
        # Fetch the URL
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(args.synth_url, follow_redirects=True)
                r.raise_for_status()
                html = r.text
        except Exception as e:
            _err(f"Cannot fetch {args.synth_url}: {type(e).__name__}: {e}")
            return 1

    # Call Schema.from_goal
    try:
        # Late import: Schema.from_goal is attached at import time, but
        # the litellm dependency is lazy (only needed when synth is used).
        from scrapex.schema_synth import _resolve_default_model

        llm_model = args.synth_model or _resolve_default_model()
    except Exception as e:
        _err(f"LLM setup failed: {e}")
        return 1

    _info(
        f"Synthesizing schema for: {args.goal!r}\n"
        f"  HTML source: {'file' if args.html_file else args.synth_url}\n"
        f"  Model: {llm_model}\n"
        f"  Cost: ~1 LLM call, ~$0.0002-$0.0008 (gpt-4o-mini)"
    )

    try:
        # Schema.from_goal is a regular sync method (returns Schema directly)
        # The method is attached at import time (monkey-patched onto Schema),
        # so mypy can't see it on the class definition — attr-defined false positive.
        schema = Schema.from_goal(  # type: ignore[attr-defined]
            goal=args.goal,
            html=html,
            llm_model=llm_model,
        )
    except Exception as e:
        _err(f"Schema synthesis failed: {type(e).__name__}: {e}")
        return 1

    # Serialize the schema as JSON
    schema_json = schema.model_dump_json(indent=2)

    # Write or print
    if args.synth_output and args.synth_output != "-":
        out_path = Path(args.synth_output)
        out_path.write_text(schema_json + "\n", encoding="utf-8")
        _info(f"Wrote schema to {args.synth_output}")
    else:
        print(schema_json)

    return 0


def _synth_main(argv: list[str]) -> int:
    """Synchronous entry for the synth subcommand."""
    parser = _build_synth_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_synth_async(args))
    except KeyboardInterrupt:
        _info("Interrupted.")
        return 130


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code.

    Exit codes follow POSIX convention:
        0 — success
        1 — scrape failed (any ``ScrapexError``, including unexpected internal errors)
        2 — bad arguments (Pydantic URL validation failure, etc.)
        130 — interrupted (SIGINT, KeyboardInterrupt)

    Parameters
    ----------
    argv:
        Optional list of CLI args. When ``None``, ``sys.argv[1:]`` is used.
        Tests pass a custom list to drive the CLI without forking a process.
    """
    # Subcommand dispatch: if argv[0] == "synth", route to _synth_main.
    # The first positional arg of scrape mode is the URL, so detecting
    # the literal string "synth" here doesn't conflict with real URLs
    # (URLs always start with a scheme like "http").
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "synth":
        return _synth_main(argv[1:])

    args = build_parser().parse_args(argv)

    # Resolve strategy: preset implies llm; --schema with selectors implies css
    # (a schema full of "name:selector" pairs is obviously CSS-shaped)
    if args.preset:
        strategy = ExtractionStrategy.LLM
    elif args.strategy != "none":
        strategy = ExtractionStrategy(args.strategy)
    elif args.schema:
        # User passed --schema without --strategy — assume CSS selectors.
        strategy = ExtractionStrategy.CSS
    else:
        strategy = ExtractionStrategy.NONE

    schema = _parse_schema(args.schema, args.description, strategy=strategy)
    if strategy == ExtractionStrategy.LLM and not schema:
        # Build a sensible default schema for LLM: ask for title + summary
        schema = Schema(
            strategy=ExtractionStrategy.LLM,
            fields=[
                FieldSpec(name="title", description="Page title or main heading"),
                FieldSpec(
                    name="summary", description="One-sentence summary of what the page is about"
                ),
            ],
        )

    # Resolve render mode
    render = RenderMode(args.render)

    # Build the request
    try:
        # llm_model: preset → that name; LLM-without-preset → sensible default
        # (user can always set OPENAI_API_KEY env var). Without this, the
        # orchestrator's LLM branch fails with "llm_model required".
        llm_model = args.preset or ("gpt-4o-mini" if strategy == ExtractionStrategy.LLM else None)
        req = ScrapeRequest(
            url=args.url,
            schema=schema,
            render=render,
            timeout_s=args.timeout,
            max_retries=args.retries,
            markdown_max_chars=args.max_chars,
            llm_model=llm_model,
            llm_region=args.region,
        )
    except Exception as e:
        _err(f"Invalid arguments: {e}")
        return 2

    # Run
    try:
        result = asyncio.run(scrape(req))
    except ScrapexError as e:
        _show_error_panel(e)
        return 1
    except KeyboardInterrupt:
        _info("Interrupted.")
        return 130
    except Exception as e:
        # Non-scrapex exceptions (e.g. playwright crash during browser
        # fallback, network stack bugs). Show a clean message instead of
        # a raw traceback so the CLI stays useful.
        wrapped = ScrapexError(
            str(e),
            hint="Unexpected internal error. Set SCRAPEX_DEBUG=1 for the full traceback.",
        )
        _show_error_panel(wrapped)
        if os.environ.get("SCRAPEX_DEBUG"):
            import traceback

            traceback.print_exc()
        return 1

    _show_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
