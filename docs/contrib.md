# Contrib modules

Opt-in helpers that ship with scrapex but are **not part of the core surface**. They're useful but specialized — read the source before using in production.

## `scrapex.contrib.sessions`

Persistent cookie jar that survives across `scrape()` calls.

```python
from scrapex.contrib.sessions import Session
from scrapex import scrape, ScrapeRequest

async def go():
    async with Session() as session:
        # Login flow (you implement this)
        await session.login(
            "https://example.com/login",
            username="...",
            password="...",
            sensitive=True,  # acknowledges the cookies are auth tokens
        )

        # Subsequent scrapes reuse the session's cookies
        result = await scrape(ScrapeRequest(
            url="https://example.com/dashboard",
            session=session,  # attaches the cookies
        ))
        print(result.markdown)
```

### Sensitive-name guard

If you pass a session without explicitly marking it sensitive, scrapex warns:

```
UserWarning: session=... was passed without sensitive=True. Cookies
for 'session=...' look like auth tokens. Set sensitive=True if this
is intentional, or strip auth cookies before passing.
```

This is a safety check, not a block. To suppress, pass `sensitive=True`.

## `scrapex.contrib.captcha`

Human-in-the-loop CAPTCHA pause/resume. Runs a local browser, shows the CAPTCHA, lets a human solve it, then continues.

```python
from scrapex.contrib.captcha import solve_captcha_human_in_loop

async def go():
    page = await some_browser.new_page()
    await page.goto("https://example.com/protected")

    if await page.locator("#captcha").count() > 0:
        await solve_captcha_human_in_loop(page, timeout_s=120)
        # User has solved the CAPTCHA in the browser window

    # Continue scraping
    html = await page.content()
```

**Not included:** automated CAPTCHA solvers (2captcha, anti-captcha). Their ToS forbids it; shipping a wrapper would push legal risk onto every user.

## What's NOT in contrib

- ❌ **Login flow wrapper** — too site-specific; would need per-site customization
- ❌ **2captcha / anti-captcha wrapper** — ToS risk
- ❌ **CAPTCHA auto-solver** — same

## Next

- [Error hints](errors.md)