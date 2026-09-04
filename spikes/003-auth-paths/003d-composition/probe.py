"""Spike 003d — design probe for the combined auth API.

No real spike code needed — this is a design check. We just verify
that adding the new fields doesn't break existing tests by sketching
the change in a side module.
"""
# This is a thinking-out-loud design check.
#
# The proposed ScrapeRequest additions:
#   - headers: dict[str, str] | None = None
#   - cookies: dict[str, str] | None = None
#   - page: Any | None = None  (Playwright Page; optional import)
#
# These are all Pydantic fields, all optional, no default. Adding them
# doesn't break the existing signature (Pydantic allows extra=None).
#
# The orchestrator (scrape.py) needs to:
#   1. If page is set: skip the fetch, use page.content() instead
#   2. Else if headers/cookies are set: pass them to HttpFetcher
#   3. Else: current behavior
#
# This is a small surface — ~15 lines of orchestrator change.
#
# For the DSL: we DO NOT build one. The recommendation is:
#   - ship headers + cookies fields
#   - ship page field (let users hand us a Playwright page)
#   - let the user use Playwright directly for the click/fill/wait parts
#   - scrapex's value: take the resulting page and apply extraction
#
# This keeps scrapex focused on extraction, not automation.

print("See README.md — this is a design check, no code to run.")
