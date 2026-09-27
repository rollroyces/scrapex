# Installation

## pip

```bash
pip install scrapex
```

## Optional extras

scrapex is lean by default (38 hard dependencies). Add extras as needed:

| Extra | What it adds | When you need it |
|---|---|---|
| `[llm]` | `litellm`, `openai`, `tiktoken` | Calling `Schema.from_goal()`, `Schema.heal()`, or using `ExtractionStrategy.LLM` |
| `[browser]` | `playwright`, `pyee` | Scraping JS-heavy pages (`render=RenderMode.BROWSER`) |
| `[stealth]` | `cloudscraper` | Bypassing Cloudflare anti-bot (`stealth=True`) |
| `[api]` | `fastapi`, `uvicorn` | Running the FastAPI wrapper for HTTP/orchestration |
| `[dev]` | everything + `pytest`, `ruff`, `mypy`, `mkdocs` | Contributing or building docs locally |

```bash
# Pick what you need
pip install 'scrapex[llm,browser]'           # typical setup
pip install 'scrapex[llm,browser,stealth]'   # full server-side
pip install 'scrapex[api]'                   # HTTP wrapper
pip install 'scrapex[dev]'                   # for contributors
```

## Verifying

```python
import scrapex
print(scrapex.__version__)  # 0.2.0
```

## Next

- [Quickstart](quickstart.md) — your first scrape in 10 seconds
- [Strategies](strategies.md) — pick the right extraction approach