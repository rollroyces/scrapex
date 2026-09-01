# scrapex

[![License: AGPL-3.0-or-later](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#tests)

**AI-friendly web scraping for Python.** `URL + schema in, clean markdown + JSON out`.

```python
import asyncio
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

async def main():
    result = await scrape(ScrapeRequest(
        url="https://example.com",
        schema=Schema(
            strategy=ExtractionStrategy.LLM,
            fields=[
                FieldSpec(name="title", description="Page title"),
                FieldSpec(name="headings", description="All top-level headings"),
            ],
        ),
    ))
    print(result.title, result.extracted)

asyncio.run(main())
```

## Why scrapex?

Most scraping libraries either:
- Force you to write brittle CSS/XPath selectors and ignore modern JS-heavy sites, **or**
- Are 80k-star monoliths with a learning curve measured in weeks.

scrapex gives you both:
- **Four extraction strategies** (CSS, XPath, Regex, LLM) with a single uniform API
- **Auto-fallback** from HTTP → browser rendering when the page is JS-only
- **Markdown-first output** so results drop straight into RAG pipelines
- **Pydantic-typed end to end** — your IDE knows every field
- **Small surface area** — the whole public API fits in one screen

## Installation

```bash
pip install scrapex                    # core (HTTP fetch + extractors)
pip install "scrapex[llm]"             # + LLM extractor (litellm)
pip install "scrapex[browser]"         # + Playwright (for JS-heavy pages)
pip install "scrapex[all]"             # everything
playwright install chromium            # one-time browser download
```

## Strategies

| Strategy | Best for | Cost | Needs |
|---|---|---|---|
| `css` | Known structure, fast/cheap | Free | nothing |
| `xpath` | Nested/conditional selectors | Free | nothing |
| `regex` | Unstructured text | Free | nothing |
| `llm` | Unknown structure, natural-language fields | $$ | `litellm` + provider key |
| `none` | Markdown only, no extraction | Free | nothing |

## Architecture

```
scrapex/
├── scrape.py            ← main entry: async scrape() orchestrator
├── models.py            ← Pydantic: ScrapeRequest, ScrapeResult, Schema, FieldSpec
├── errors.py            ← typed exceptions
├── fetchers/            ← HTTP (httpx) + Browser (Playwright)
├── processing/          ← HTML → Markdown → chunks
└── extractors/          ← CSS / XPath / Regex / LLM (swappable via protocol)
```

Borrowed from the best of [crawl4ai](https://github.com/unclecode/crawl4ai)
(strategy pattern), [scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai)
(natural-language schema), and [browser-use](https://github.com/browser-use/browser-use)
(clean plugin extension). Drops the parts you don't need.

## Examples

### CSS — fast & deterministic
```python
result = await scrape(ScrapeRequest(
    url="https://shop.example.com/widget",
    schema=Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="name", selector="h1.product-name"),
            FieldSpec(name="price", selector="span.price", attr="data-amount"),
            FieldSpec(name="in_stock", selector=".stock-status"),
        ],
    ),
))
```

### LLM — when the structure varies
```python
result = await scrape(ScrapeRequest(
    url="https://news.example.com/article",
    schema=Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[
            FieldSpec(name="headline", description="Article headline"),
            FieldSpec(name="author", description="Article author name"),
            FieldSpec(name="published", description="ISO 8601 publish date"),
        ],
    ),
    llm_model="gpt-4o-mini",
    llm_api_key="...",  # or set OPENAI_API_KEY env var
))
```

### Auto — let scrapex pick the fetcher
```python
# Tries HTTP first; if the page is empty or looks JS-only, falls back to browser.
result = await scrape("https://spa.example.com/")  # render=RenderMode.AUTO by default
```

### Markdown for RAG
```python
from scrapex.processing import chunk_markdown

result = await scrape("https://docs.example.com/guide")
chunks = chunk_markdown(result.markdown, max_chars=1500, overlap=150)
# → ready for embedding + vector store ingestion
```

## License

**AGPL-3.0-or-later** + commercial licensing.

AGPL means: free to use, modify, and self-host. If you offer scrapex as a
network service, you must release your source under AGPL.

For closed-source / SaaS embedding without AGPL obligations, a commercial
license is available — contact **licensing@rollroyces.dev**.

This mirrors the [MariaDB Business Source License](https://mariadb.com/bsl11/)
model and matches the licensing strategy of [py-idp](https://github.com/rollroyces/py-idp).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run tests with:

```bash
pip install -e ".[dev]"
pytest -v
```

## Credits

Inspired by [crawl4ai](https://github.com/unclecode/crawl4ai),
[scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai),
[browser-use](https://github.com/browser-use/browser-use),
and [firecrawl](https://github.com/firecrawl/firecrawl).