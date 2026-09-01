"""Examples using scrapex with China-hosted LLM providers.

Run any of these with:

    # DeepSeek (cheapest)
    DEEPSEEK_API_KEY=sk-... python examples/china_llm_examples.py deepseek-v3

    # Zhipu GLM (long-context, free tier)
    ZAI_API_KEY=... python examples/china_llm_examples.py glm-flash

    # Moonshot Kimi (long context)
    MOONSHOT_API_KEY=... python examples/china_llm_examples.py kimi-v1-128k --region cn

Each block runs against example.com (always reachable). For real scraping,
swap the URL.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from scrapex import (
    ExtractionStrategy,
    FieldSpec,
    RenderMode,
    Schema,
    ScrapeRequest,
    china,
    scrape,
)


async def scrape_with_preset(preset_name: str, *, region: str = "intl") -> None:
    """Scrape example.com using a China LLM preset."""
    preset = china.get(preset_name)
    print(f"Preset: {preset.name}")
    print(f"  model: {preset.model}")
    print(f"  provider: {preset.provider}")
    print(f"  tier: {preset.tier}")
    print(f"  region: {region}")

    # Confirm a key is available before we hit the network
    key = china.discover_api_key(preset.provider)
    if not key:
        print(
            f"\n✗ No API key set for {preset.provider}. "
            f"See README env-var table for which env var to set."
        )
        sys.exit(1)
    print(f"  api_key: {key[:8]}… (auto-discovered)")

    base = china.api_base_for(preset.provider, region)  # type: ignore[arg-type]
    if base:
        print(f"  api_base: {base}")

    result = await scrape(ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.LLM,
            fields=[
                FieldSpec(
                    name="purpose",
                    description="The stated purpose of the example.com page",
                ),
            ],
        ),
        llm_model=preset_name,  # preset name, resolved internally
        llm_region=region,       # type: ignore[arg-type]
        render=RenderMode.HTTP,  # skip auto-fallback for this demo
    ))
    print(f"\nExtracted: {result.extracted}")
    print(f"Elapsed: {result.elapsed_ms}ms")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "preset",
        choices=[
            "deepseek-v3",
            "glm-4.7",
            "glm-flash",
            "qwen-flash",
            "kimi-v1-128k",
            "doubao-flash",
        ],
        help="Which China LLM preset to demo",
    )
    parser.add_argument(
        "--region",
        choices=["intl", "cn"],
        default="intl",
        help="API region (mainland China vs international)",
    )
    args = parser.parse_args()

    await scrape_with_preset(args.preset, region=args.region)


if __name__ == "__main__":
    asyncio.run(main())
