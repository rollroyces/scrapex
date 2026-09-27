# Cloudflare / anti-bot bypass

scrapex ships an opt-in stealth fetcher for sites behind Cloudflare. Activate it per-request:

```python
import asyncio
from scrapex import scrape, ScrapeRequest

result = asyncio.run(scrape(ScrapeRequest(
    url="https://example.com/",
    stealth=True,  # route through cloudscraper
)))
```

## Install

```bash
pip install 'scrapex[stealth]'
```

This pulls in [`cloudscraper`](https://github.com/VeNoMouS/cloudscraper) (~6.7k stars, MIT-licensed). cloudscraper handles the JS challenge that Cloudflare serves to headless clients and returns the cookies you need to load the actual page.

## When to use

- `stealth=False` (default) — fast HTTP fetch via httpx. No anti-bot bypass.
- `stealth=True` — route through cloudscraper. Adds ~5-10ms but bypasses Cloudflare's free tier.

!!! warning
    `stealth=True` is bypass for **Cloudflare's free-tier JS challenge**,
    not for **enterprise-grade anti-bot** services (DataDome, PerimeterX,
    Akamai Bot Manager). Those need residential proxies or browser
    fingerprinting — neither of which scrapex attempts.

## How it composes with `render`

| `render` | `stealth=True` | What happens |
|---|---|---|
| `HTTP` | ✅ | httpx-style request through cloudscraper |
| `BROWSER` | ❌ (ignored) | Playwright handles anti-bot on its own |
| `AUTO` | ✅ | If HTTP fails transiently, falls back to browser (stealth ignored there) |

## Performance

cloudscraper adds ~5-10ms per request for the Cloudflare challenge handling. Not free, but cheaper than spinning up a browser.

## What scrapex does NOT do

- ❌ No captcha solving (anti-captcha.com, 2captcha violate their ToS — scrapex doesn't ship a wrapper)
- ❌ No residential proxy rotation
- ❌ No browser fingerprinting
- ❌ No TLS fingerprint randomization

For serious anti-bot work, scrapex is the wrong tool. Use ScrapingBee, Bright Data, or similar managed services.

## Next

- [China LLM providers](china-llm.md)
- [Contrib modules](contrib.md)