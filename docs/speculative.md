# Speculative features

scrapex has a few features that were built without measurement. **Use with care.**

## What's speculative

| Feature | File | Status |
|---|---|---|
| `scrapex.selector_rank._rank_selectors()` | `scrapex/selector_rank.py` | Built per user request; not in public API |
| `scrapex.page_classify.classify_page()` | `scrapex/page_classify.py` | Built per user request; not in public API |

Both files exist in the codebase but are **not exported** from `scrapex/__init__.py` and **not covered by the test suite** with real-world inputs.

## Why they're speculative

These features were built before being measured:

- `selector_rank` — adds an LLM call to rank CSS selectors. Untested hypothesis: ranking helps small models pick the right selector.
- `page_classify` — classifies a page as `DISCLAIMER` / `FORM` / `LIST` / `DETAIL` / `SEARCH` / `UNKNOWN`. Untested hypothesis: classification enables smarter default schemas.

Neither has been benchmarked against real pages with a real LLM.

## What this means for users

You probably shouldn't import these. They're in the codebase so that:

1. The work isn't lost if measurement proves them valuable
2. Other contributors can pick up the measurement work

If you do want to experiment, import them directly:

```python
from scrapex.selector_rank import _rank_selectors
from scrapex.page_classify import classify_page_v2

# Not part of the public API; behavior may change without notice
```

## Removal in v0.3.0

If benchmarks (run by the maintainer) show no value, these will be removed in v0.3.0. Don't depend on them in production code.

## Honest caveats

- The hypothesis that these features help is **unverified**.
- Code without measurement is technical debt, not progress.
- If you find a real-world case where these would help, please open an issue with reproducible evidence — that's how they graduate from speculative to stable.

## Next

- [Contrib modules](contrib.md)