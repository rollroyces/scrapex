# Spike 003 — Auth paths (all four options)

## Honest take first

Before we ship anything, here's the negative case:

**None of the four "let scrapex do auth" approaches is competitive with what already exists.** If you need real browser automation with login flows, browser-use (112k stars) is purpose-built and battle-tested. If you just need cookies, httpx has `cookies=` already. If you need a fluent DSL, Playwright's API is already fluent.

**What scrapex CAN do honestly:** add a tiny surface that lets users hand scrapex an authenticated state (headers, cookies, or a pre-built Playwright page) so they get scrapex's extraction without leaving their existing auth workflow. We add maybe 30 lines. We do NOT become a second browser-use.

## Sub-spike results

| Spike | Approach | Verdict | Key finding |
|---|---|---|---|
| **003a** | Headers / cookies | **VALIDATED** | `ScrapeRequest` rejects `headers=...` and `cookies=...` with `extra_forbidden` Pydantic error. Adding them is straightforward. |
| **003b** | Headless browser | **VALIDATED** | Login+click+extract works in raw Playwright in 13 lines, 0.79s. A wrapper doesn't make it shorter. |
| **003c** | Browser automation DSL | **INVALIDATED** | My naive DSL was 5 lines LONGER than raw Playwright. Real value only emerges when the user reuses the same browser across many calls. |
| **003d** | Composition | **CLEAN** | `headers`, `cookies`, and `page` fields can all be added to `ScrapeRequest` without breaking the existing API. ~15 lines of orchestrator change. |

## What scrapex should actually ship

**Two small additions, not a DSL:**

1. **`headers: dict[str, str] \| None`** on `ScrapeRequest` — for users who
   already have a session cookie / bearer token. Pass through to httpx.

2. **`cookies: dict[str, str] \| None`** on `ScrapeRequest` — for users who
   want to pass cookies as a dict (cleaner than manually building the
   `Cookie:` header). httpx's `cookies=` kwarg handles this.

**For the headless case (login + click + PDF):** the right answer is
**"let users hand us a Playwright Page"**. The user runs Playwright
themselves (with their login flow), then calls `scrape(ScrapeRequest(
url=target, page=their_page))` to extract from the page they already
have. No DSL, no automation framework, no scope creep.

The `page` field is a small addition too — `Any | None = None`, the
orchestrator checks `if req.page: html = req.page.content(); else: fetch()`.

## Action items

If we ship this:

- [ ] Add `headers: dict[str, str] \| None = None` to `ScrapeRequest`
- [ ] Add `cookies: dict[str, str] \| None = None` to `ScrapeRequest`
- [ ] Add `page: Any \| None = None` to `ScrapeRequest`
- [ ] Update `HttpFetcher.fetch()` to accept `headers` and `cookies`
- [ ] Update orchestrator to skip fetch if `page` is set
- [ ] Add tests for: header auth, cookie auth, page-injection, all composed
- [ ] Update README "Authentication" section with examples for all three

## Verdict

- 003a: **VALIDATED** — feature is needed; implementation is small.
- 003b: **VALIDATED** — workflow is feasible; don't ship a wrapper.
- 003c: **INVALIDATED** — DSL doesn't pay for itself in code reduction.
- 003d: **CLEAN** — composition is straightforward.

**Recommended action:** ship 003a (headers+cookies) and 003d (page
injection). Skip 003c (DSL). Defer full browser-automation features
to v2.0 when there's user demand.