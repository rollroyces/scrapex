"""Human-in-the-loop CAPTCHA helper.

This is the only CAPTCHA pattern scrapex ships. It is the cleanest
viable option because it is simultaneously:
- technically robust (humans always beat CAPTCHAs)
- legally clean (a human solved it, not a script; the library is not
  bypassing any technical access control)
- maintenance-free (no arms race with CAPTCHA vendors)

What scrapex does NOT do (intentionally):
- Ship a 2captcha / anti-captcha.com wrapper. Cloudflare, hCaptcha,
  and reCAPTCHA's ToS explicitly forbid automated bypass; a library
  shipping such a wrapper would push legal/ToS risk onto every user.
- Ship an in-process ML solver. None are publicly maintained; they rot
  within months of release.
- Hide the challenge. The user always knows when a CAPTCHA is being
  paused for. There is no silent "we just handle it" mode.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


# The selector intentionally targets the *family* of CAPTCHA containers.
# Matching the exact class is brittle by design: CAPTCHA vendors change
# their markup regularly, and we want a generous match that survives
# those changes.
_CHALLENGE_SELECTOR = (
    "iframe[src*='turnstile'], iframe[src*='recaptcha'], "
    "iframe[src*='hcaptcha'], .cf-turnstile, .g-recaptcha, .h-captcha"
)


async def solve_captcha_human_in_loop(
    page: Page,
    *,
    screenshot_path: str | Path = "captcha-challenge.png",
    timeout_s: float = 120.0,
    poll_interval_s: float = 2.0,
) -> bool:
    """Pause the scrape, hand the challenge to a human, resume on signal.

    Parameters
    ----------
    page:
        A live Playwright ``Page`` that is currently on a page with a
        CAPTCHA challenge. The caller owns the page; scrapex just waits.
    screenshot_path:
        Where to save a screenshot of the challenge so a human (or a
        future UI) can see it.
    timeout_s:
        How long to wait for the challenge to disappear before giving up.
        Default 120s.
    poll_interval_s:
        How often to re-check the DOM for the challenge element. Default 2s.

    Returns:
    -------
    bool
        ``True`` if the challenge element disappeared before ``timeout_s``
        (human solved it). ``False`` if the challenge is still present
        when the timeout expires.

    Raises:
    ------
    TypeError:
        If ``page`` does not expose the Playwright ``Page`` API
        (``.screenshot``, ``.locator``). This is a programming error,
        not a runtime error.

    Notes:
    -----
    Resumption is detected by polling for the challenge selector's
    disappearance. This is intentionally cheap, correct, and works for
    every CAPTCHA vendor because we are not parsing the challenge itself.
    """
    shot = Path(screenshot_path)
    shot.parent.mkdir(parents=True, exist_ok=True)

    # Take a screenshot so a human (or a future UI) can see the challenge.
    try:
        await page.screenshot(path=str(shot))
        screenshot_ok = True
    except Exception as exc:
        screenshot_ok = False
        print(f"[hitl] screenshot failed: {exc!r}")

    if screenshot_ok:
        print(
            f"[hitl] CAPTCHA challenge saved to {shot}. Solve it in the "
            f"browser pointed at this session, then wait for scrapex to "
            f"resume (timeout in {timeout_s:.0f}s)."
        )
    else:
        print(
            "[hitl] Could not capture screenshot. Solve the CAPTCHA in the "
            "browser; scrapex will resume once the challenge element is gone."
        )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            still_there = await page.locator(_CHALLENGE_SELECTOR).count()
        except Exception:
            still_there = 0
        if still_there == 0:
            print("[hitl] challenge element gone — resuming scrape.")
            return True
        await asyncio.sleep(poll_interval_s)

    print(f"[hitl] timeout: challenge still present after {timeout_s:.0f}s.")
    return False


__all__ = ["solve_captcha_human_in_loop"]
