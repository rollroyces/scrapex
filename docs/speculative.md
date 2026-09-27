# Speculative features

scrapex previously shipped a few features that were built without measurement. **They were removed in v0.2.1.**

## What was removed

| Feature | Removed in | Reason |
|---|---|---|
| `scrapex.selector_rank._rank_selectors()` | v0.2.1 | Built without measurement; no evidence the LLM call improved selector quality |
| `scrapex.page_classify.classify_page()` | v0.2.1 | Built without measurement; the regex-based v1 had a known bug (returned "unknown" on disclaimer pages); the BS4-based v2 wasn't benchmarked |

## Why they were removed

These features were built before being measured:

- `selector_rank` — adds an LLM call to rank CSS selectors. Untested hypothesis: ranking helps small models pick the right selector.
- `page_classify` — classifies a page as `DISCLAIMER` / `FORM` / `LIST` / `DETAIL` / `SEARCH` / `UNKNOWN`. Untested hypothesis: classification enables smarter default schemas.

Neither was benchmarked against real pages with a real LLM. Code without measurement is technical debt, not progress.

## Lesson

If you find a feature in scrapex that you'd like to add but isn't proven, the right approach is:

1. Build it
2. **Measure it** with `tests/integration/test_heal_live.py` or a similar harness
3. If measurement proves it helps → graduate to the public API with docs
4. If measurement is inconclusive or negative → don't ship it

The previous workflow of "build it, label it speculative, ship it" was wrong. Speculative code in the codebase has no accountability — it just sits there until someone removes it.

## If you need these features back

The git history has them (commits before v0.2.1). If you have a real use case and benchmark data showing they help, file an issue with reproducible evidence and we can reintroduce them properly.