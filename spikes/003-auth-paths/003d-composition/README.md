# Spike 003d — Composition: can all three approaches coexist?

## Question

**Can `ScrapeRequest` accept all three auth approaches (headers, cookies,
or a pre-existing Playwright session) without breaking the existing API?**

The proposed `fetcher` field would be the cleanest way to let users
hand scrapex an authenticated browser context.

## Design sketch

```python
# Option A: cookie/header injection (cheapest)
await scrape(ScrapeRequest(url=url, headers={"Cookie": "session=abc"}))

# Option B: hand us a Playwright Page
async with browser_session() as page:
    await page.goto(login_url)
    await page.fill(...); await page.click(...)
    await page.goto(target_url)
    result = await scrape(ScrapeRequest(url=target_url, page=page))
    # The fetcher reuses the existing page instead of fetching
```

The key question: does `page=...` in ScrapeRequest break any existing
tests? Does it complicate the orchestrator's choice of fetcher?

## Approach

Just sketch the design — no need to run code, the question is about
interface design. Confirm the existing tests still pass with the new
fields added (a, b).

## Verdict

This is more of a design exercise than a probe. If the design is clean,
we move to implementing it. If it's ugly, we drop the feature.