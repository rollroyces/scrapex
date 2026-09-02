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

## Try it in 10 seconds — `python -m scrapex`

The fastest way to see what scrapex does:

```bash
# Just get clean markdown (no schema needed)
python -m scrapex https://example.com

# CSS extraction with a one-liner schema
python -m scrapex https://shop.example.com/widget \
    --schema "title:h1.product-name,price:span.price:data-amount"

# LLM extraction with a China preset (DeepSeek key auto-discovered)
DEEPSEEK_API_KEY=sk-... \
    python -m scrapex https://news.example.com/article \
    --preset deepseek-v3 --region cn

# Browser-mode for JS-only pages
python -m scrapex https://spa.example.com --render browser
```

Output is a Rich-formatted panel with status, extracted fields, warnings,
and a markdown preview. Failures show a red panel with the error and a
**hint** suggesting what to try next:

```
╭─────────────────────────────────── Error ────────────────────────────────────╮
│ [https://x.com/missing] HTTP 404                                              │
│                                                                              │
│ hint: Page not found. If the site is JS-rendered, try render=browser.         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Set `SCRAPEX_DEBUG=1` to get a full traceback alongside the error panel.

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
├── errors.py            ← typed exceptions with status-aware hints
├── fetchers/            ← HTTP (httpx) + Browser (Playwright)
├── processing/          ← HTML → Markdown → chunks
├── extractors/          ← CSS / XPath / Regex / LLM (swappable via protocol)
├── __main__.py          ← `python -m scrapex <url>` interactive CLI (Rich)
└── china_llm.py         ← Curated presets for China-hosted LLM providers
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

### China LLM providers — curated presets

`scrapex.china_llm` ships curated presets for the major China-hosted LLM providers. Just pass the preset name as `llm_model` and the right `api_key`, `api_base`, and model string are auto-resolved:

```python
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

result = await scrape(ScrapeRequest(
    url="https://example.com",
    schema=Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[FieldSpec(name="title", description="Page title")],
    ),
    llm_model="deepseek-v3",          # preset name, not raw litellm string
    # DEEPSEEK_API_KEY env var is auto-discovered
))
```

Available presets (verified against litellm docs 2026-09-01):

| Preset | Provider | Tier | Notes |
|---|---|---|---|
| `glm-4.7` | Zhipu (Z.AI) | flagship | 200K context, reasoning |
| `glm-4.6` | Zhipu (Z.AI) | mid | 200K context |
| `glm-flash` | Zhipu (Z.AI) | free | free tier, 128K context |
| `qwen-max` | Alibaba QwenCloud | flagship | international Qwen |
| `qwen-plus` | Alibaba QwenCloud | mid | balanced cost/quality |
| `qwen-flash` | Alibaba QwenCloud | fast | high-volume scraping |
| `qwen-turbo` | Alibaba DashScope | fast | legacy DashScope prefix |
| `deepseek-v3` | DeepSeek | mid | strong general, cheap |
| `deepseek-reasoner` | DeepSeek | mid | chain-of-thought, slower |
| `kimi-v1-8k` | Moonshot | fast | short context, cheap |
| `kimi-v1-128k` | Moonshot | mid | long context, big pages |
| `doubao-flash` | ByteDance Volcengine | fast | fast + cheap |

Region routing for mainland China (Moonshot + Qwen have separate `.cn` endpoints):

```python
result = await scrape(ScrapeRequest(
    url="...",
    schema=...,
    llm_model="kimi-v1-128k",
    llm_region="cn",          # routes to api.moonshot.cn automatically
    # MOONSHOT_API_KEY env var is auto-discovered
))
```

Env-var discovery per provider (first one set wins):

| Provider | Env vars (priority order) |
|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` |
| Qwen | `QWENCLOUD_API_KEY` → `QWEN_AI_PLATFORM_API_KEY` → `DASHSCOPE_API_KEY` |
| Zhipu (Z.AI) | `ZAI_API_KEY` |
| Moonshot | `MOONSHOT_API_KEY` |
| Volcengine | `VOLCENGINE_API_KEY` → `ARK_API_KEY` |

**Not yet supported** (verified absent from current litellm provider list or unstable):
Baidu Wenxin / ERNIE, Hunyuan, Spark, MiniMax. PRs welcome once upstream integration is stable.

You can also import presets directly:

```python
from scrapex import china

# All presets, sorted flagship → free
for preset in china.presets():
    print(preset.name, preset.tier, preset.description)

# One preset
preset = china.deepseek_v3()
print(preset.model)   # "deepseek/deepseek-chat"
print(preset.provider)  # "deepseek"

# Resolve to litellm kwargs (model, api_key, optional api_base)
kwargs = china.resolve("kimi-v1-128k", region="cn")
# {'model': 'moonshot/moonshot-v1-128k', 'api_key': '...', 'api_base': 'https://api.moonshot.cn/v1'}
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