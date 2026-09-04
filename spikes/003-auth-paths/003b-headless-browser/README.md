# Spike 003b — Headless browser with login + click

## Question

**Given a workflow like "go to /login, fill the form, click submit,
navigate to /dashboard, find the PDF link, click it, extract the link" —
can scrapex describe this in a clean, structured way?**

This is the "captcha + click + PDF" workflow the user described. The
goal isn't to build a full automation framework — it's to see if
scrapex can offer a thin wrapper over Playwright that:
- exposes a small DSL (goto, fill, click, wait_for, extract)
- works with the same `Schema` system as CSS extraction
- is opt-in (browser deps stay optional)

## Given/When/Then

- **Given** a mock site with a login form + a dashboard with a PDF link
- **When** the user calls `await browser_session.run(steps=[...]).extract(schema)`
- **Then** the steps execute, the final page is parsed, and fields are extracted

## Approach

This is exploratory — the goal is to see if a thin DSL is even useful
before designing it. We'll build the smallest possible "session" wrapper
and measure how much code the user has to write vs. raw Playwright.

## Verdict target

✅ if: <30 lines of user code to express a login + click + extract workflow
⚠️ if: works but requires >50 lines
❌ if: doesn't work / is too much complexity