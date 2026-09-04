# Spike 004a — Login-flow automation — VERDICT

**Verdict: PARTIAL** — 21 → 8 lines (-62%, *clears the 30% bar*), but the
wrapper has to ship its own session/cookie/download machinery to make the
flow that short, and that machinery is exactly where scrapex's extraction
niche ends. The savings are real for this one workflow but the wrapper
would be a net addition to scrapex's maintenance surface.

## How to reproduce

```bash
cd /Users/hermes/scrapex
source .venv/bin/activate
python spikes/004a-login-flow/probe.py
```

Output from this run:

```
OK: raw=33B wrapper=33B
RAW    Playwright : 21 non-blank/non-comment lines
WRAP   scrapex    :  8 non-blank/non-comment lines
delta             : 13 lines (+61.9%)
```

Both implementations drive the same aiohttp mock server (login form →
302 → cookie-gated dashboard → "Download PDF" link). End-to-end run is
real: real HTTP, real Chromium, real file bytes downloaded and compared
byte-for-byte.

## What got shorter

The wrapper hides exactly three pieces of Playwright boilerplate:

1. **Browser lifecycle.** `async_playwright()` context manager +
   `launch` + `new_context` + `new_page` + `try/finally browser.close()`
   collapses into `async with BrowserSession() as b:`.
2. **Form submit + redirect handling.** `await page.click` +
   `wait_for_url` becomes a single `b.submit(selector, "/dashboard")`
   that wraps `expect_navigation`.
3. **File download extraction.** The 4-line
   `expect_download` → `path()` → `open()` → `read()` dance becomes
   `b.download("#pdf") → bytes`.

That third one is the largest single saving (5 raw lines → 1 wrapper line),
because Playwright's `expect_download` API is genuinely awkward.

## What got longer / what's hidden

The 8-line wrapper body stands on **45 lines of `BrowserSession` class
plus `__aenter__/__aexit__`** that the user does not see. Spread over a
single flow that ratio is great. Spread over the dozens of flows scrapex
would need to support (file uploads, drag-and-drop, multi-tab,
frames/shadow DOM, dialogs, network interception, custom headers,
proxy auth, captcha handoff), that class grows into a permanent
maintenance burden that *competes with* scrapex's actual job of HTML
extraction.

Also: the wrapper **trades Playwright's flexibility for terseness**.
In raw Playwright, `wait_for_url("**/dashboard")` is a glob; in the
wrapper it's a substring. In raw Playwright, `expect_download` can save
to a custom path with `download.save_as(path)`; the wrapper returns
bytes into memory. Fine for a 33-byte PDF, wrong for a 200MB report.

## Honest assessment

- **The line reduction is real (62%) and clears the 30% bar.**
- **The wrapper is honest, runnable, and correct for this one flow.**
- **But the savings come from a 45-line class that would have to grow**
  every time someone wants a feature Playwright already has.
  scrapex's stated niche is *extraction*, not *automation*. The cost
  of the wrapper lives in maintenance, not in caller lines, and that
  cost belongs in a project whose whole reason for existing is browser
  automation (browser-use, playwright-python's own recipes,
  Microsoft's Playwright MCP, etc.) — all of which already exist with
  more momentum than scrapex can bring to bear.

If scrapex *does* ship a wrapper, the shape that produced the savings
is:

```python
class BrowserSession:
    async def __aenter__(self): ...   # own async_playwright + browser + ctx + page
    async def __aexit__(self, *e): ...  # browser.close() + pw.stop()

    async def goto(self, url) -> Self
    async def fill(self, selector, value) -> Self
    async def submit(self, selector, wait_url) -> Self   # wraps expect_navigation
    async def text(self, selector) -> str
    async def download(self, selector) -> bytes           # wraps expect_download + path + read
```

…and the rule is: **only ship this once the extraction primitives
(`extract_one`, `extract_many`, `extract_table`) can consume a
`BrowserSession` directly** so the user gets one chain
`session.fill(...).submit(...).extract(...)` rather than two layers of
abstraction. Until then, this is a wrapper in search of a second
customer.

## Recommendation

**Do not ship a login-flow wrapper in the current spike.** File this
under "valid technique, wrong project." If a future spike (004b captcha,
004c sessions) keeps hitting the same wrapper demand from real users,
reopen this question with the second-customer evidence in hand.

## Files

- `probe.py` — mock server, both flows, AST-based LoC counter, end-to-end
  assertion
- `README.md` — this file
