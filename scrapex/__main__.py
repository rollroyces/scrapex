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
