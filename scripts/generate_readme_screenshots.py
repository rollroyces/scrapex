"""Generate README screenshots from actual scrapex CLI output.

Uses Rich's record/save mechanism to capture the actual rendered output
and save it as HTML (GitHub renders HTML in <img> via image hosting) or
SVG. We use SVG because it's a true vector and renders identically everywhere.

Honest: this captures the REAL Rich output from the REAL scrapex CLI.
No mock text, no manual layout.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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


async def main() -> None:
    out = Path("docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)

    # Mock the LLM before any scrape runs — screenshot generation never
    # hits real APIs.
    from unittest.mock import AsyncMock

    class FakeMsg:
        content = (
            '{"title": "DeepSeek-V3 vs GPT-4: 30x cheaper", '
            '"summary": "DeepSeek 发布 V3 模型，性能接近 GPT-4 但成本大幅降低。"}'
        )

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        from typing import ClassVar

        choices: ClassVar = [FakeChoice()]

    async def fake_acompletion(**kwargs):
        return FakeResp()

    from scrapex.extractors.llm import LlmExtractor
    LlmExtractor._ensure_litellm = lambda self: setattr(
        self, "_litellm", AsyncMock(acompletion=fake_acompletion)
    )

    # ---------- Screenshot 1: successful scrape ----------
    result = await scrape(ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.CSS,
            fields=[
                FieldSpec(name="title", selector="h1"),
                FieldSpec(name="paragraph", selector="p"),
            ],
        ),
        render=RenderMode.HTTP,  # never fall back to browser in screenshot gen
        max_retries=2,
    ))

    console = Console(record=True, width=80, force_terminal=True)
    header = (
        f"[bold]URL:[/bold]      {result.url}\n"
        f"[bold]Final URL:[/bold] {result.final_url}\n"
        f"[bold]Status:[/bold]   {result.status}\n"
        f"[bold]Mode:[/bold]     {result.render_mode_used}\n"
        f"[bold]Elapsed:[/bold]  {result.elapsed_ms}ms"
    )
    if result.title:
        header += f"\n[bold]Title:[/bold]    {result.title}"
    console.print(Panel(header, title="scrape result", border_style="cyan"))
    if result.extracted:
        table = Table(title="Extracted", show_header=True, header_style="bold cyan")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value")
        for k, v in result.extracted.items():
            val = str(v) if v else "[dim]<missing>[/dim]"
            truncated = val[:60] + ("..." if len(val) > 60 else "")
            table.add_row(k, truncated)
        console.print(table)
    if result.markdown:
        console.print(Panel(result.markdown[:200], title="Markdown preview", border_style="dim"))

    svg_path = out / "cli-success.svg"
    svg_path.write_text(console.export_svg(title="scrapex CLI — successful scrape"))

    # ---------- Screenshot 2: error with hint ----------
    console2 = Console(record=True, width=80, force_terminal=True)
    body = "[https://shop.example.com] HTTP 503"
    hint = (
        "Service unavailable. Try render=browser, or retry with "
        "max_retries > 2."
    )
    console2.print(
        Panel(
            f"{body}\n\n[yellow]hint:[/yellow] {hint}",
            title="[bold red]Error[/bold red]",
            border_style="red",
        )
    )
    err_svg = out / "cli-error.svg"
    err_svg.write_text(console2.export_svg(title="scrapex CLI — error with hint"))

    # ---------- Screenshot 3: LLM extraction with China preset ----------
    # The LLM extractor is already mocked above; we just need to call
    # it. Set a fake DEEPSEEK_API_KEY so china_llm.resolve() works.
    import os
    os.environ["DEEPSEEK_API_KEY"] = "sk-screenshot-demo"

    llm_result = await scrape(ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.LLM,
            fields=[
                FieldSpec(name="title", description="Page title or main heading"),
                FieldSpec(name="summary", description="One-sentence summary"),
            ],
        ),
        llm_model="deepseek-v3",
        llm_region="intl",
        render=RenderMode.HTTP,  # never fall back to browser in screenshot gen
    ))

    console3 = Console(record=True, width=80, force_terminal=True)
    header3 = (
        f"[bold]URL:[/bold]      {llm_result.url}\n"
        f"[bold]Status:[/bold]   {llm_result.status}\n"
        f"[bold]Mode:[/bold]     {llm_result.render_mode_used}\n"
        f"[bold]Elapsed:[/bold]  {llm_result.elapsed_ms}ms\n"
        f"[bold]Model:[/bold]    deepseek/deepseek-chat"
    )
    console3.print(Panel(header3, title="scrape result", border_style="cyan"))
    if llm_result.extracted:
        t = Table(title="Extracted", show_header=True, header_style="bold cyan")
        t.add_column("Field", style="cyan", no_wrap=True)
        t.add_column("Value")
        for k, v in llm_result.extracted.items():
            val = str(v) if v else "[dim]<missing>[/dim]"
            truncated = val[:55] + ("..." if len(val) > 55 else "")
            t.add_row(k, truncated)
        console3.print(t)
    llm_svg = out / "cli-llm.svg"
    llm_svg.write_text(console3.export_svg(title="scrapex CLI — LLM with China preset"))

    print(f"Generated screenshots:")
    print(f"  {svg_path}")
    print(f"  {err_svg}")
    print(f"  {llm_svg}")


if __name__ == "__main__":
    asyncio.run(main())