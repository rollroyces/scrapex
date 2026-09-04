# Spike 003c — Browser automation DSL: worth it?

## Question (sharpened by 003b)

**For a thin DSL on top of Playwright to be worth building, it has
to measurably reduce the user's code. 003b showed raw Playwright
needs 13 lines for a login+click+extract. Does a fluent-chain DSL
beat that?**

## Approach

Try a real DSL design: `BrowserSession` with a fluent chain
(`goto`, `fill`, `click`, `wait`, `extract`). Measure line count and
readability against raw Playwright.

## Honest priors

- browser-use (112k stars) is exactly this — full agent loop
- scrapex's niche is **single-page extraction** with 4 strategies
- Adding agent-style automation is a 10x scope expansion
- The right move is probably to let users **plug in their own
  Playwright session** to `ScrapeRequest`, not build a DSL

## Verdict target

This spike is exploratory. If the DSL doesn't beat raw Playwright by
at least 30%, the recommendation is "don't build it" — let users
hand us a Playwright `Page` and just do the extraction.