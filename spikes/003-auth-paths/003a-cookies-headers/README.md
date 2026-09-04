# Spike 003a — Cookie/header injection

## Question

**Can a `ScrapeRequest` carry a session cookie / bearer token and have it
work end-to-end with the existing `HttpFetcher`?**

This is the cheapest possible auth solution: the user pre-authenticates
(out of band, e.g. logs in via browser, exports cookie, passes to scrapex)
and scrapex just sends those headers.

## Given/When/Then

- **Given** a URL that requires a `Cookie: session=abc123` header
- **When** the user passes that cookie via a new `headers={}` field on `ScrapeRequest`
- **Then** the `HttpFetcher` includes it in the request, and the server returns 200

If true, we add one field to the model — zero new infrastructure.
If false (e.g. cookies alone aren't enough because the session is bound to
TLS fingerprint or fingerprinting), we need full browser automation (003b).

## Approach

1. Add `headers: dict[str, str] | None` to `ScrapeRequest` (Pydantic model).
2. Pass `headers=...` to `HttpFetcher.fetch()`.
3. Test against a real authenticated endpoint.

For the test target, we need a site that:
- returns different content with/without a specific cookie
- doesn't require full browser fingerprinting (so this test is honest)

Quick options:
- `httpbin.org/cookies/set?k=v` — sets a cookie, then `/cookies` echoes it
- A local mock HTTP server (httptest in Python)

Going with a local mock server — no network dependency, deterministic.

## Verdict target

✅ if: a single `headers={...}` field makes auth work for "give me a cookie" sites.
⚠️ if: works for headers but not cookies (we'd need cookie-jar handling).
❌ if: even headers don't help (we'd need full browser).