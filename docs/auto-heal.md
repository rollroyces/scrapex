# Auto-heal

scrapex detects when a site redesigned its DOM and breaks your saved CSS selectors. When a browser-rendered scrape returns empty for every field, `scrape()` calls `Schema.heal()` once to patch the schema, then re-extracts.

## What it does

```python
import asyncio
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy, RenderMode

# Saved schema with selectors that no longer match (the site redesigned)
stale = Schema(
    strategy=ExtractionStrategy.CSS,
    fields=[FieldSpec(name="title", selector="h1.OLD-CLASS-2024")],
)

result = asyncio.run(scrape(ScrapeRequest(
    url="https://example.com/",
    schema=stale,
    render=RenderMode.BROWSER,  # auto-heal only fires on browser-rendered pages
    llm_model="gpt-4o-mini",    # needed for the heal call
)))

# If the LLM could patch the selector, result.extracted["title"] is filled.
# If not, result.extracted is empty and result.extraction_warnings has a hint.
```

## Disabling

```python
result = asyncio.run(scrape(ScrapeRequest(url=..., schema=..., auto_heal=False)))
```

## Cost

| Component | Tokens |
|---|---|
| Prompt template (fixed) | ~196 |
| Fields JSON | ~25 per field |
| Cleaned HTML payload | ~600–5000 (depends on page size) |
| Output | ~50 |
| **Real cost per call** | **~$0.0002–$0.0008** (gpt-4o-mini) |

Hard-capped at 1 retry. No recursion — preserves the single-page contract.

## When it fires

Auto-heal triggers when **all** of these are true:

- `req.auto_heal = True` (default)
- Schema has fields
- Strategy is CSS / XPath / Regex (not LLM, not NONE)
- Page was browser-rendered (`page.render_mode == "browser"`)
- Extraction returned empty for every field

## When it skips

| Condition | Why |
|---|---|
| Strategy is `LLM` | The LLM is the extractor; empty = "no data on page", not "schema broken" |
| Page was HTTP-fetched only | Most likely needs JS to render; CSS-selector heal can't fix that — would just waste tokens |
| Schema has no fields | Nothing to extract, nothing to heal |
| Extraction is partial | Some fields filled — conservatively we don't risk corrupting working selectors |

## Honest caveats

- **Silent-failure mode is possible.** The LLM may produce selectors that *look* correct but match the wrong DOM element. The `auto-healed` warning means "I tried" not "I verified."
- **Real-LLM heal quality is unmeasured** in this sandbox. Run `tests/integration/test_heal_live.py` with `OPENAI_API_KEY` to measure before trusting on production data.

## Next

- [Error hints](errors.md) — what the warnings in `extraction_warnings` mean
- [Speculative features](speculative.md) — features built but not measured