# CAPTCHA-solving landscape survey

Short, honest survey of every realistic option for solving CAPTCHAs from
Python. For each: what it is, what it costs, legal/ToS risk, and whether
scrapex should ship it.

---

## 1. Paid human+ML solving services (2captcha, anti-captcha.com, CapMonster, SolveCaptcha, NoCaptchaAI)

**What it is.** You POST the challenge metadata (sitekey + pageurl) to a
commercial service, get back a token ~2-30s later. The service runs a mix
of human workers (in low-wage jurisdictions) and ML models on the back
end. Officially supported Python SDKs exist for the big four:
[`2captcha/2captcha-python`](https://github.com/2captcha/2captcha-python),
[`anti-captcha/anticaptcha-python`](https://github.com/anti-captcha/anticaptcha-python),
`capmonster`, `solvecaptcha`. Costs are around **$1–3 per 1000 solves**:
2captcha lists Cloudflare Turnstile at $1.45/1000 with ~2s solve time
(see `2captcha.com/p/cloudflare-turnstile`). Anti-Captcha lists Turnstile
at similar rates.

**Legal/ToS risk.** **High.** Every major ToS (Cloudflare, hCaptcha,
reCAPTCHA, DataDome, PerimeterX) explicitly forbids bypassing their
challenges. The services themselves aren't illegal to operate (they sell
access to *human labor*), but using them to bypass a site's CAPTCHA
likely violates that site's ToS, and after *Van Buren v. United States*
(2021) CFAA liability is narrower but not zero — bypassing technical
access controls on sites that gate content behind CAPTCHAs is exactly
the grey zone courts have left open. Cloudflare in particular has
pursued aggressive civil action against bypass operators.

**Viability for scrapex.** Technically trivial: ~50 lines of code using
the official SDK. But the moment we ship a working integration we make
scrapex a **CAPTCHA-bypass service** in the eyes of upstream sites.
Every scrapex user inherits the legal/ToS risk. We would also need to
absorb ongoing maintenance as Cloudflare/hCaptcha rotate challenge
schemas (every few months).

---

## 2. In-process ML solvers (open source)

**What it is.** Local ML models that attempt to classify/solve the
challenge without an external service. Examples: `yescaptcha`,
`NopeCHA` (closed-source binary), `captcha-recognizer` (image-only),
various GitHub projects that wrap the `capsolver` API. There is no
publicly maintained, working ML solver for reCAPTCHA v3 / Cloudflare
Turnstile / hCaptcha — the people who build those are the same teams
running the paid services above, and they don't open-source the models.

**Cost.** Engineering time to find + integrate + keep working. Model
weights themselves (where they exist) are 100MB+ downloads.

**Legal/ToS risk.** Same as (1) — the ToS risk is on the *user*, not
the library, but the library is enabling it.

**Viability for scrapex.** **None.** Models rot in months (per the
spike spec — "any solver that worked last year is now broken"). Even
*building* one is research-grade work. The spec explicitly says don't
do it.

---

## 3. Browser-fingerprinting countermeasures (Cloudflare bypass, stealth browsers)

**What it is.** Make your automated browser *look like* a real user so
the CAPTCHA is never shown in the first place. Tools in this category:
`undetected-chromedriver`, `playwright-extra` with stealth plugin,
`camoufox`, `CloakBrowser` (source-level Chromium patches),
`browserless.io`, `BrowserCat`. The goal is to avoid the challenge, not
solve it.

**Cost.** Free (open-source) to $$ (managed stealth browsers).

**Legal/ToS risk.** **Medium.** You're not bypassing an explicit
challenge; you're spoofing the headers/fingerprints that trigger one.
Most anti-bot ToS still forbid "automated access," and the line is
blurry. Court treatment is similar to (1): nobody has been prosecuted
just for `User-Agent` spoofing, but it's contractually disallowed.

**Viability for scrapex.** **Already orthogonal.** Scrapex's existing
fetchers can use a real browser via Playwright; the *browsers* are
patched externally. Scrapex shouldn't ship a stealth-browser — it
should let users bring their own. (See verdict in README.md.)

---

## 4. "Human-in-the-loop" (HIL) pattern

**What it is.** Pause the scrape when a CAPTCHA appears, surface the
challenge to a human operator (screenshot + click-to-solve or a future
UI), resume once the challenge is gone. No external service, no ML
model, no fingerprint spoofing. Just `page.screenshot()` → wait →
resume.

**Cost.** Free (in code). Operationally expensive — requires a human
on call — but that's the user's problem, not the library's.

**Legal/ToS risk.** **Lowest.** A *human* solved the CAPTCHA. The
library never pretended otherwise. The ToS risk shifts to whatever the
user does with the *data* afterwards (and that risk already exists for
any scraping).

**Viability for scrapex.** **Clean and honest.** The API surface is
~30 lines: `async def solve_captcha_human_in_loop(page, *, timeout_s)`
that screenshots, polls for the challenge element to disappear, and
returns. Works with any browser-driven fetcher that exposes a
Playwright `page` object. The spike's `probe.py` demonstrates the
exact signature.

---

## Summary table

| Option | Cost | Legal/ToS | Maintainable | Ship in scrapex? |
|---|---|---|---|---|
| Paid service wrapper | $1-3 / 1000 | High | Brittle (challenge schema drift) | No — shifts risk to users |
| In-process ML | Engineering | High | No (rot in months) | No — explicitly out of scope |
| Stealth browsers | Free–$$ | Medium | External concern | Already orthogonal |
| Human-in-the-loop | Free (in code) | Low | Yes (CAPTCHA-agnostic) | **Yes — only honest option** |

The probe (see `probe.py`) demonstrates the HIL pattern. It does not
demonstrate the paid-service wrapper beyond proving the *request shape*
of the 2captcha API works (we hit `/res.php` with a fake task id; the
service returns a JSON error without consuming credits).
