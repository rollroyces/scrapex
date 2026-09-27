# scrapex

AI-friendly web scraping for Python — URL + schema in, clean markdown + JSON out.

```python
import asyncio
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

req = ScrapeRequest(
    url="https://example.com/product",
    schema=Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.product-title"),
            FieldSpec(name="price", selector="span.price", attr="data-amount"),
        ],
    ),
)

result = asyncio.run(scrape(req))
print(result.markdown)   # cleaned markdown of the page
print(result.extracted)  # {"title": "...", "price": "..."}
```

## Why scrapex

Single-page extraction library. URL + optional natural-language goal → extracted fields + markdown + metadata. Built for AI/RAG pipelines where you want clean data, not noisy HTML.

**Deliberately narrow:**

- Fetches ONE URL, returns ONE response
- Uses LLMs ONLY for one-shot schema synthesis (`Schema.from_goal`) and debugging (`Schema.heal`, `Schema.explain`)
- No multi-page crawling, no agent loops, no click automation

**Lean dependencies:** 38 hard dependencies, opt-in `[llm]`, `[browser]`, `[stealth]`, `[api]` extras.

## Installation

```bash
pip install scrapex              # core
pip install scrapex[llm]         # + LLM schema synthesis
pip install scrapex[browser]     # + JS rendering via Playwright
pip install scrapex[stealth]     # + Cloudflare bypass
pip install scrapex[api]         # + FastAPI wrapper
pip install scrapex[dev]         # + tests, lint, docs build
```

## Quick tour

| Feature | Where |
|---|---|
| Single-page fetch + extract | [Quickstart](quickstart.md) |
| CSS / XPath / Regex extraction | [Strategies](strategies.md) |
| LLM-synthesized schemas | [Quickstart](quickstart.md) |
| Auto-heal on redesign | [Auto-heal](auto-heal.md) |
| China-hosted LLMs | [China LLM providers](china-llm.md) |
| Cloudflare bypass | [Cloudflare bypass](cloudflare.md) |
| Cookie sessions | [Contrib modules](contrib.md) |
| Human-in-the-loop captcha | [Contrib modules](contrib.md) |
| HTTP / n8n integration | [Quickstart](quickstart.md#http-api) |
| Error messages with hints | [Error hints](errors.md) |

## License

AGPL-3.0-or-later + commercial dual license. See [LICENSE](https://github.com/rollroyces/scrapex/blob/main/LICENSE) on GitHub.