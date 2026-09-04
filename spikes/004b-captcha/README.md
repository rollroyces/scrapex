# Spike 004b — Verdict: CAPTCHA solving

## Verdict: **INVALIDATED** for paid-service and in-process ML wrappers. **VALIDATED** for human-in-the-loop as an optional helper.

scrapex should **NOT** ship a `solve_captcha(service="2captcha", ...)` wrapper.
scrapex **MAY** ship a `solve_captcha_human_in_loop(page)` helper, behind an
explicit opt-in flag, with documentation that names the legal/ToS risk the
user is taking on.

---

## What the probe showed

`probe.py` (run with `python probe.py`) does three things, none of which
spend money or hit a real CAPTCHA:

1. **Probe 1 — API shape verification.** Hits 2captcha's public
   `/res.php` with a deliberately fake task id. The service returns a
   JSON error without consuming credits. This proves the request shape
   (URL, params, response) is what the published docs claim. The
   `2captcha/2captcha-python` SDK would be a thin wrapper around
   exactly this pattern.

2. **Probe 2 — paid-service signature demo.** Calls
   `solve_captcha_via_service(page, service="2captcha", ...)` with the
   shape the spec asked for and confirms it raises
   `NotImplementedError` with an honest "this is a stub" message that
   points users at 2captcha / anti-captcha.com's own docs. The point:
   this is the API surface scrapex *could* expose, but it currently
   refuses to on purpose.

3. **Probe 3 — HIL signature demo.** Runs
   `solve_captcha_human_in_loop(page, screenshot_path=..., timeout_s=...)`
   against a fake page object. Confirms the function: takes a
   screenshot, prints operator instructions, polls for the challenge
   selector to disappear, returns a bool. No real browser is launched
   (we're a spike, not an integration test), but the contract is
   correct and the polling/selector logic is the same one a real
   scrapex would use.

The probe output ends with a literal `[hitl] challenge element gone —
resuming scrape.` line, which is what the eventual user-visible log
message would look like.

---

## Honest legal/ToS assessment

- **Paid-service wrappers** make scrapex a CAPTCHA-bypass service. Every
  scrapex user inherits the ToS risk of whichever site they target.
  Cloudflare's ToS explicitly forbids bypassing Turnstile; so does
  hCaptcha's; so does reCAPTCHA's. Civil liability has historically
  chased operators (Cloudflare vs. bypass services) more than users,
  but the risk is real and growing.
- **CFAA / `Van Buren` (2021).** Public-page scraping is generally
  *not* a CFAA violation after *hiQ v. LinkedIn*, but bypassing
  technical access controls is the part courts have left open. CAPTCHA
  bypass sits squarely in that grey zone. We are not lawyers.
- **In-process ML.** Same ToS risk as paid services, plus a
  maintenance burden the spec correctly flags as unworkable.
- **Human-in-the-loop.** A human solved the CAPTCHA. The library is
  not "bypassing" anything — it's a screenshot tool plus a wait. The
  *user* is responsible for what they do with the data afterward,
  which is the same risk they already have.

---

## Recommendation

**scrapex should NOT ship a paid-service wrapper.** Reasons:

1. It makes scrapex look like a CAPTCHA-bypass tool. Maintainers
   become a target for abuse complaints from Cloudflare, hCaptcha,
   PerimeterX.
2. The legal/ToS risk is real and growing.
3. The integration is trivial (`pip install 2captcha-python`, ~20
   lines). Users who need it can do it themselves in their application
   code. There's no reason the *library* has to do it.
4. The challenge schemas rotate every few months. We'd be maintaining
   a perpetual arms race.

**scrapex SHOULD ship `solve_captcha_human_in_loop(page)`** as an
optional helper, behind `scrapex.contrib.captcha` or similar, with:

- Documentation naming the legal risk.
- A clear log message every time it pauses ("a CAPTCHA was detected,
  pausing for human input").
- No defaults that auto-pause (so users opt in).
- The ~30-line implementation shown in `probe.py`.

This is the cleanest path: a library that helps users *not* have to
write the same pause-screenshot-wait loop themselves, without making
scrapex itself a CAPTCHA-bypass tool.

**scrapex should ALSO leave room for stealth browsers.** Scrapex's
existing Playwright fetcher already supports a real browser; the user
can swap in `playwright-extra-stealth`, `camoufox`, or `BrowserCat`
without scrapex doing anything. That's the right boundary.

---

## Final verdict

| Component | Verdict | Why |
|---|---|---|
| `solve_captcha(service="2captcha", ...)` wrapper | **INVALIDATED** | Legal/ToS risk; trivial to do outside the library |
| In-process ML solver | **INVALIDATED** | Out of scope; models rot; spec says don't |
| Stealth-browser integration | **ORTHOGONAL** | User brings their own browser; scrapex doesn't ship one |
| `solve_captcha_human_in_loop(page)` | **VALIDATED** | Clean, honest, low-risk; ~30 LOC |

See `landscape.md` for the full survey and `probe.py` for the
demonstration.
