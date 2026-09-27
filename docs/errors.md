# Error hints

scrapex exceptions know what to try next. Each error class carries a `hint` attribute with actionable advice.

```python
import asyncio
from scrapex import scrape, ScrapeRequest
from scrapex.errors import FetchError

async def go():
    try:
        result = await scrape(ScrapeRequest(url="https://x.com/missing"))
    except FetchError as e:
        print(f"fetch failed: {e}")
        print(f"hint: {e.hint}")

asyncio.run(go())
```

## Common errors

| Exception | When | Hint |
|---|---|---|
| `FetchError` | HTTP fetch failed | Check the URL, status code, and whether `render=RENDER_MODE.BROWSER` would help |
| `RenderError` | Browser render failed | Often a missing Playwright install; `playwright install chromium` |
| `ExtractionError` | All extractors failed | Usually means the schema is too strict; try `Schema.heal()` or `Schema.from_goal()` |
| `ConfigurationError` | Missing dep / config | `pip install 'scrapex[llm]'` or set `OPENAI_API_KEY` |

## Status-aware hints in the CLI

```bash
scrapex https://example.com
```

If something goes wrong, the CLI shows a Rich-formatted table with the status code, error, and suggested next step.

## Warning vs error

Most failures surface as **warnings** in `result.extraction_warnings` rather than exceptions:

```python
result = await scrape(ScrapeRequest(url="..."))
for w in result.extraction_warnings:
    print(w)
```

Common warnings:

- `required field 'X' was not found` — your schema has a `required=True` field that the page didn't have
- `schema auto-healed: ...` — the LLM patched your selectors and re-extraction succeeded
- `auto-heal failed: <ExceptionType>` — the LLM call failed; check your `llm_model` and API key

## Next

- [Contrib modules](contrib.md)