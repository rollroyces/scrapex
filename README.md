# scrapex

> **AI-friendly web scraping for Python.** URL + schema in, clean markdown + JSON out.

```bash
pip install scrapex
```

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
                FieldSpec(name="summary", description="One-sentence summary"),
            ],
        ),
    ))
    print(result.title, result.extracted)

asyncio.run(main())
```

---

## Contents

- [Try it in 10 seconds](#try-it-in-10-seconds)
- [Why scrapex](#why-scrapex)
- [Installation](#installation)
- [Quickstart: the CLI](#quickstart-the-cli)
- [Quickstart: Python API](#quickstart-python-api)
- [Extraction strategies](#extraction-strategies)
- [China LLM providers](#china-llm-providers)
- [Error hints](#error-hints)
- [Architecture](#architecture)
- [Development](#development)
- [License](#license)
- [Credits](#credits)

---

## Try it in 10 seconds

No Python required. Pick your shell:

```bash
# Just clean markdown
python -m scrapex https://example.com

# CSS extraction with a one-liner schema
python -m scrapex https://shop.example.com/widget \
    --schema "title:h1.product-name,price:span.price:data-amount"

# LLM extraction with a China preset
DEEPSEEK_API_KEY=sk-... \
    python -m scrapex https://news.example.com/article \
    --preset deepseek-v3 --region cn

# Browser-mode for JS-only pages
python -m scrapex https://spa.example.com --render browser
```

Output:

```
╭─────────────────────────────── scrape result ────────────────────────────────╮
│ URL:      https://example.com/                                               │
│ Status:   200                                                                │
│ Mode:     http                                                               │
│ Elapsed:  136ms                                                              │
│ Title:    Example Domain                                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
                                   Extracted
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field     ┃ Value                                                            │
│ paragraph │ This domain is for use in documentation examples without…   │
└───────────┴──────────────────────────────────────────────────────────────────┘
```

---

## Why scrapex

Most scraping libraries force you to choose between:

| Approach | What you get | What you give up |
|---|---|---|
| **Selector-based** (Scrapy, BeautifulSoup) | Fast, free, deterministic | Brittle CSS; breaks on JS-heavy sites |
| **Agent/LLM-based** (Firecrawl, scrapegraph) | Handles arbitrary structure | Slow, costs tokens, opaque |
| **Browser automation** (Playwright, browser-use) | Renders JS | Heavy; needs a browser |

scrapex gives you all three behind one uniform API:

- **Four extraction strategies** — `css`, `xpath`, `regex`, `llm` — choose per page, not per project
- **Auto-fallback** — HTTP first; if the page is JS-only, fall back to Playwright automatically (only on transient errors; 4xx never wastes a retry)
- **Markdown-first output** — drops straight into RAG pipelines; no extra processing
- **Pydantic-typed end to end** — your IDE knows every field
- **China LLM presets** with mainland-region routing and auto env-var discovery
- **Interactive CLI** with Rich-formatted output and **status-aware error messages**
- **AGPL-3.0-or-later + commercial** license — same model as [py-idp](https://github.com/rollroyces/py-idp)

The whole public API fits in one screen.

---

## Installation

```bash
# Core (HTTP fetch + extractors)
pip install scrapex

# Optional extras
pip install "scrapex[llm]"           # + LLM extractor (litellm)
pip install "scrapex[browser]"       # + Playwright (JS-heavy pages)
pip install "scrapex[all]"           # everything

playwright install chromium          # one-time, only if using [browser]
```

Requires Python 3.10+. No system-level dependencies.

---

## Quickstart: the CLI

The CLI is the fastest way to see what scrapex does. Full help:

```
$ python -m scrapex --help
usage: scrapex [-h] [--strategy {css,xpath,regex,llm,none}] [--schema SCHEMA]
               [--preset PRESET] [--region {intl,cn}] [--render {http,browser,auto}]
               [--timeout TIM] [--retries RETRIES] [--max-chars MAX_CHARS]
               url
```

| Flag | | Example |
|---|---|---|
| `--strategy` | Extraction strategy | `--strategy css` |
| `--schema` | Comma-separated `name:selector[:attr]` fields | `--schema "title:h1,price:span:data-amount"` |
| `--preset` | China LLM preset (implies `--strategy llm`) | `--preset deepseek-v3` |
| `--region` | `intl` or `cn` for mainland China | `--region cn` |
| `--render` | `http`, `browser`, or `auto` | `--render browser` |

---

## Quickstart: Python API

```python
import asyncio
from scrapex import scrape, ScrapeRequest

async def main():
    # 1. Just markdown — no schema needed
    result = await scrape("https://example.com")
    print(result.markdown)

    # 2. CSS extraction
    from scrapex import Schema, FieldSpec, ExtractionStrategy
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

    # 3. LLM extraction (gpt-4o-mini, OpenAI key from OPENAI_API_KEY env var)
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
    ))

asyncio.run(main())
```

Every public type is Pydantic — your IDE auto-completes every field and validates arguments at the call site.

---

## Extraction strategies

| Strategy | Best for | Cost | Needs |
|---|---|---|---|
| `css` | Known structure, fast and deterministic | Free | — |
| `xpath` | Nested / conditional selectors | Free | — |
| `regex` | Unstructured text, no DOM needed | Free | — |
| `llm` | Unknown structure, natural-language fields | $$ (tokens) | `litellm` + provider key |
| `none` | Markdown only, no extraction | Free | — |

**Choosing per page, not per project** — the strategy lives in the request, so the same scraper handles both structured product pages and unstructured news articles without code changes.

---

## China LLM providers

`scrapex.china_llm` ships 12 curated presets across the major China-hosted providers. Pass the preset name as `llm_model` and the right `api_key`, `api_base`, and model string are auto-resolved:

```python
result = await scrape(ScrapeRequest(
    url="...",
    schema=...,
    llm_model="deepseek-v3",          # preset name, not a raw litellm string
    # DEEPSEEK_API_KEY env var is auto-discovered
))
```

### Presets

| Preset | Provider | Tier | Context |
|---|---|---|---|
| `glm-4.7` | Zhipu (Z.AI) | flagship | 200K, reasoning |
| `glm-4.6` | Zhipu (Z.AI) | mid | 200K |
| `glm-flash` | Zhipu (Z.AI) | **free** | 128K |
| `qwen-max` | Alibaba QwenCloud | flagship | — |
| `qwen-plus` | Alibaba QwenCloud | mid | — |
| `qwen-flash` | Alibaba QwenCloud | fast | — |
| `qwen-turbo` | Alibaba DashScope | fast | — |
| `deepseek-v3` | DeepSeek | mid | 64K |
| `deepseek-reasoner` | DeepSeek | mid | 64K, chain-of-thought |
| `kimi-v1-8k` | Moonshot | fast | 8K |
| `kimi-v1-128k` | Moonshot | mid | 128K |
| `doubao-flash` | ByteDance Volcengine | fast | — |

### Region routing for mainland China

Moonshot and Qwen have separate `.cn` endpoints. Set `llm_region="cn"` and scrapex picks the right `api_base` automatically:

```python
result = await scrape(ScrapeRequest(
    url="...",
    schema=...,
    llm_model="kimi-v1-128k",
    llm_region="cn",          # → api.moonshot.cn (not api.moonshot.ai)
    # MOONSHOT_API_KEY env var is auto-discovered
))
```

### Env-var discovery

For each provider, scrapex scans the right env vars in priority order — first one set wins:

| Provider | Env vars (priority order) |
|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` |
| Qwen | `QWENCLOUD_API_KEY` → `QWEN_AI_PLATFORM_API_KEY` → `DASHSCOPE_API_KEY` |
| Zhipu (Z.AI) | `ZAI_API_KEY` |
| Moonshot | `MOONSHOT_API_KEY` |
| Volcengine | `VOLCENGINE_API_KEY` → `ARK_API_KEY` |

### Direct API

You can also work with presets directly without scraping:

```python
from scrapex import china

# Iterate all presets (flagship → free)
for preset in china.presets():
    print(preset.name, preset.tier)

# One preset
preset = china.deepseek_v3()
print(preset.model)       # "deepseek/deepseek-chat"
print(preset.provider)    # "deepseek"

# Resolve to litellm kwargs (model, api_key, optional api_base)
kwargs = china.resolve("kimi-v1-128k", region="cn")
# → {'model': 'moonshot/moonshot-v1-128k',
#    'api_key': '...',
#    'api_base': 'https://api.moonshot.cn/v1'}
```

**Not yet supported:** Baidu Wenxin / ERNIE, Hunyuan, Spark, MiniMax — absent from the current litellm provider list. PRs welcome once upstream integration is stable.

---

## Error hints

Every error class knows what to try next:

```python
from scrapex import scrape, ScrapeRequest
from scrapex.errors import FetchError

try:
    await scrape(ScrapeRequest(url="https://x.com/missing"))
except FetchError as e:
    print(e)      # "[https://x.com/missing] HTTP 404"
    print(e.hint) # "Page not found. If the site is JS-rendered, try render=browser."
```

| Error | Default hint |
|---|---|
| `FetchError(404)` | "Page not found. If the site is JS-rendered, try render=browser." |
| `FetchError(429)` | "Rate limited. Increase delay between requests or rotate proxies." |
| `FetchError(5xx)` | "Try render=browser, or retry with max_retries > 2." |
| `FetchError(no status)` | "Transport-level failure (DNS, TLS, or timeout). Try increasing timeout_s." |
| `RenderError` | "pip install 'scrapex[browser]' && playwright install chromium" |
| `ConfigurationError` | "Check the README for required environment variables." |

Hints can be overridden per-instance: `FetchError(url, msg, status=404, hint="my custom message")`.

---

## AI-synthesized schemas (Schema.from_goal)

The only "AI magic" in scrapex. Describe what you want in one sentence
and an LLM produces the schema for you:

```python
from scrapex import Schema, ScrapeRequest, scrape

schema = Schema.from_goal(
    "extract the report title, price, and PDF download link",
    html=html,
)
result = await scrape(ScrapeRequest(url=..., schema=schema))

# The schema is just a normal Schema object — explain() shows why
# the LLM picked each selector (audit it before relying on it):
for line in schema.explain():
    print(line)
# title: h1.report-title is the only h1 with class="report-title"
# price: span.price was the only element matching the price pattern
# link: a.download was the anchor with download attr
```

**How it picks the LLM.** Order:

1. `OLLAMA_HOST` set (or Ollama running locally) → `ollama/qwen2.5:1.5b`
   (free, runs on your laptop, no API key).
2. `OPENAI_API_KEY` set → `gpt-4o-mini`.
3. Neither → `ConfigurationError` with install hint.

Pass `llm_model="..."` to override.

**Install the optional extra first:**

```bash
pip install scrapex[llm]
```

**Design guarantees (read these before relying on it):**

- **Opt-in only.** `Schema(strategy=..., fields=...)` still works
  without touching an LLM. Zero LLM cost on the default path.
- **Lenient.** Never raises on empty extraction. The user gets a
  working Schema back even if the LLM hallucinated; the warning is
  in `UserWarning` and in `schema.explain()`.
- **Transparent.** `schema.explain()` returns one line per field
  explaining why the LLM picked that selector. The user owns the
  schema after `from_goal()` returns.
- **Cached.** Identical `(html, goal, model)` pairs return cached
  results within the process.

**What it's NOT:**

- Not a replacement for hand-written schemas on critical pages.
- Not a competitor to scrapegraph-ai (which runs the full LLM
  pipeline). We just synthesize a Schema and stop.
- Not magic. Sometimes the LLM picks a bad selector. Always review
  the result before relying on it in production.

## Optional contrib modules

scrapex ships two **opt-in** helpers under `scrapex.contrib.*`. They are
explicitly named to make the "this is community-grade, audit before
using" contract obvious. Read the source before putting them in
production.

### `scrapex.contrib.sessions` — persistent cookies across calls

```python
import asyncio
from scrapex import ScrapeRequest, Schema, FieldSpec, ExtractionStrategy
from scrapex.contrib.sessions import Session

async def main():
    async with Session() as s:
        # 1. Login once — server sets cookies that go into the session jar
        await s.scrape("https://example.com/login")
        # 2. All subsequent scrape() calls reuse the same cookies
        result = await s.scrape(ScrapeRequest(
            url="https://example.com/dashboard",
            schema=Schema(
                strategy=ExtractionStrategy.CSS,
                fields=[FieldSpec(name="title", selector="h1")],
            ),
        ))
        print(result.extracted, s.list())  # value-free cookie snapshot
```

**Security baseline:** cookies are never logged. Setting a cookie with a
sensitive name (`session`, `auth`, `token`, `csrf`, `xsrf`, `sid`,
`password`, `secret`, `api_key`) without `sensitive=True` emits a
`UserWarning` — the value is never included in the warning text.

### `scrapex.contrib.captcha` — human-in-the-loop CAPTCHA pause

scrapex does **not** ship a CAPTCHA solver. The only honest pattern is
human-in-the-loop: pause, take a screenshot, wait for a human to solve
it, then resume.

```python
from scrapex.contrib.captcha import solve_captcha_human_in_loop

# page is a live Playwright Page that hit a CAPTCHA
solved = await solve_captcha_human_in_loop(page, timeout_s=120)
if solved:
    # challenge is gone — continue scraping
    ...
```

Returns `True` if the challenge element disappeared before the timeout
(default 120s), `False` otherwise. Saves a screenshot to
`captcha-challenge.png` by default so the operator can see the challenge.

We do **not** ship a 2captcha / anti-captcha.com wrapper. Their ToS
explicitly forbid automated bypass; a library shipping such a wrapper
would push legal/ToS risk onto every user.

## Architecture

```
scrapex/
├── scrape.py            async scrape() orchestrator
├── models.py            Pydantic: ScrapeRequest, ScrapeResult, Schema, FieldSpec
├── errors.py            typed exceptions with status-aware hints
├── schema_synth.py      Schema.from_goal() — LLM synthesizes a schema from a goal
├── fetchers/            HTTP (httpx) + Browser (Playwright)
├── processing/          HTML → Markdown → chunks (RAG-friendly)
├── extractors/          CSS / XPath / Regex / LLM (swappable via protocol)
├── china_llm.py         China-region LLM presets (DeepSeek / Qwen / GLM / ...)
├── contrib/             opt-in helpers (read source before using)
│   ├── captcha.py       human-in-the-loop CAPTCHA pause/resume
│   └── sessions.py      cookie-jar session that persists across scrape() calls
├── __main__.py          python -m scrapex — interactive CLI (Rich)
└── china_llm.py         12 curated presets for China-hosted LLM providers
```

The extractor pattern is borrowed from [crawl4ai](https://github.com/unclecode/crawl4ai);
the natural-language schema idea from [scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai);
the plugin extensibility from [browser-use](https://github.com/browser-use/browser-use).
Drops the parts you don't need.

---

## Development

```bash
git clone https://github.com/rollroyces/scrapex
cd scrapex
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest -v                      # full suite (~10s)
pytest --cov=scrapex           # with coverage
ruff check scrapex tests       # lint
mypy scrapex                   # type check

# Try the CLI against a live URL
python -m scrapex https://example.com

# Run the China LLM demo (needs an API key)
DEEPSEEK_API_KEY=sk-... python examples/china_llm_examples.py deepseek-v3
```

**Test coverage:** 255 tests across 11 test files. **91% line coverage** on the source.
mypy clean across 13 source files.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

---

## License

**AGPL-3.0-or-later** + commercial licensing.

AGPL means: free to use, modify, and self-host. If you offer scrapex as a
network service, you must release your source under AGPL.

For closed-source / SaaS embedding without AGPL obligations, a commercial
license is available — contact **licensing@rollroyces.dev**.

This mirrors the [MariaDB Business Source License](https://mariadb.com/bsl11/)
model and matches the licensing strategy of [py-idp](https://github.com/rollroyces/py-idp).

---

## Credits

Inspired by [crawl4ai](https://github.com/unclecode/crawl4ai),
[scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai),
[browser-use](https://github.com/browser-use/browser-use),
and [firecrawl](https://github.com/firecrawl/firecrawl).