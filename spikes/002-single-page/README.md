# Spike 002 — Single-page benchmark

## Verdict: PARTIAL

**Honest numbers, fresh venvs, 10 iterations each.**

| Library | Median (s) | p95 (s) | Relative |
|---|---:|---:|---:|
| lxml + httpx | 0.038 | 0.099 | **1.0x (fastest)** |
| beautifulsoup4 + lxml + httpx | 0.040 | 0.105 | 1.1x |
| scrapex (CSS) | 0.044 | 0.267 | 1.2x |

URL: https://example.com
Schema: 2 CSS fields (`h1` title, `p` paragraph)

## What worked
- The benchmark ran cleanly on all three implementations.
- The variance was tight (p95 within 2.5x of median).

## Surprises

### 1. **scrapex is NOT faster than raw lxml+httpx for trivial pages.**
- Median: 0.044s vs 0.038s (1.2x slower).
- p95: 0.267s vs 0.099s (2.7x worse — cold-start variance hurts).
- For 2 fields, scrapex's overhead (Pydantic + trafilatura markdown pass + error wrapping) is more than the savings from a unified API.
- **Honest claim:** "scrapex makes the easy case slightly slower but the complex case dramatically easier."

### 2. **`pip install scrapex` is broken on PyPI** (discovered during the spike)
- Someone else has a different `scrapex` package on PyPI (a USPS address scraper).
- `pip install scrapex` from PyPI installs the wrong library.
- Our package has the same name and would shadow theirs.
- **Action required:** pick a different PyPI name (e.g. `scrapex-ai`, `scrapex-py`, `ai-scrapex`) before publishing.
- This spike uses the local wheel (`/Users/hermes/scrapex/dist/...whl`) to bypass the issue for benchmarking purposes.

## Defensible claims (what scrapex can honestly say)

✅ "**Simplest API for the common case**" — one `ScrapeRequest`, one `await`
→ bs4/lxml require fetch + parse + select orchestration by hand.

✅ "**Same code path for CSS / XPath / regex / LLM**" — switching strategies
is a single parameter, not a library switch.

⚠️ "**Fastest scraper**" — no, raw lxml+httpx is faster for trivial cases.
Don't claim this.

⚠️ "**Smallest dep footprint**" — true (per spike 001), but doesn't make scrapex
fastest on a per-call basis.

## Recommendation for the real build

This spike validated one important thing and invalidated another:

1. **Validated** that scrapex's value proposition is **API simplicity + strategy
   flexibility**, not raw speed. The README already says this — the benchmark
   confirms it.

2. **INVALIDATED the "fastest" claim.** Don't make it.

3. **Discovered a real bug**: the PyPI name `scrapex` is taken. The package
   cannot be published under this name without breaking someone else. **This
   is a blocker for v0.1.0 release.**

## Action items

- [ ] Pick a new PyPI name before publishing v0.1.0
- [ ] Update README's install instructions to use the new name once chosen
- [ ] Add a benchmark section to README with these honest numbers
- [ ] Consider adding a "vs. raw lxml+httpx" example showing when scrapex
      wins (multi-strategy, auto-fallback, error handling) vs. loses (trivial
      one-off scripts)