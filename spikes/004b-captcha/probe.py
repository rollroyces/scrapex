"""Spike 004b — CAPTCHA solving probe.

The probe does NOT call any paid CAPTCHA service and does NOT download or
run any ML solver. The honest, smallest thing that could possibly work is
a stubbed public-API surface that demonstrates what `scrapex.solve_captcha`
would look like, what it would need, and why it is currently a stub.

Two probes are demonstrated:

1. `solve_captcha_via_service(page, service, api_key)` — the paid-service
   wrapper. Calls 2captcha's public /res.php endpoint with a deliberately
   bogus task id and proves the request shape works end-to-end without
   spending credits (2captcha returns an error JSON we can inspect).

2. `solve_captcha_human_in_loop(page)` — the HITL probe. Saves a
   screenshot, prints instructions to the operator, waits up to N seconds
   for the challenge to disappear from the DOM, and returns. This is the
   cleanest possible "honest" pattern: no ML, no paid service, no
   pretending.

Both probes run without side effects beyond local files and stdout.
Neither modifies the scrapex library.

Run: `python probe.py`
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


# --- Probe 1: paid-service wrapper (stub) ---------------------------------

async def solve_captcha_via_service(
    page: Any,
    *,
    service: str = "2captcha",
    api_key: str,
    sitekey: str,
    pageurl: str,
    timeout_s: float = 30.0,
) -> str:
    """Stub of `scraper.solve_captcha(page, service=..., api_key=...)`.

    Returns the solved token string. Raises NotImplementedError with an
    honest message because shipping this would (a) make scrapex implicitly
    a CAPTCHA-bypass service, (b) push legal/ToS risk onto every user,
    and (c) require paid credits we are not buying in a spike.

    The shape below mirrors the 2captcha Turnstile API documented at
    https://2captcha.com/p/cloudflare-turnstile — see landscape.md.

    To prove the *request shape* works without spending money, we still
    hit the public 2captcha /res.php endpoint with a fake task id; the
    server returns a JSON error we can inspect (no credit is consumed).
    """
    raise NotImplementedError(
        "scrapex does not ship CAPTCHA solving. The function signature is "
        "shown here so the API surface can be reviewed. To use 2captcha or "
        "anti-captcha.com, call them directly from your application code; "
        "see https://2captcha.com/p/cloudflare-turnstile and "
        "https://anti-captcha.com/apidoc."
    )


def _probe_request_shape_2captcha() -> dict:
    """Hit 2captcha's public /res.php with a fake task id.

    This does NOT consume credits — it just verifies that the URL, query
    parameters, and JSON error response shape are what 2captcha publishes.
    Returns the parsed response dict.
    """
    # Same parameters the official Python client sends, see:
    # https://github.com/2captcha/2captcha-python (in.php / res.php)
    params = {
        "key": "PROBE-NOT-A-REAL-KEY",
        "action": "get",
        "id": "999999999999",
        "json": "1",
    }
    url = f"https://2captcha.com/res.php?{urlencode(params)}"
    with urlopen(url, timeout=15) as resp:  # noqa: S310 - explicit external call
        body = resp.read().decode("utf-8", errors="replace")
    # We don't json.loads here on purpose: a paid account would never get
    # this exact error string, and the point is to *see* what 2captcha
    # returns when a task id is unknown.
    return {"url": url, "status_code": resp.status, "body": body}


# --- Probe 2: human-in-the-loop (cleanest viable pattern) -----------------

async def solve_captcha_human_in_loop(
    page: Any,
    *,
    screenshot_path: str | Path = "captcha-challenge.png",
    timeout_s: float = 120.0,
    poll_interval_s: float = 2.0,
) -> bool:
    """Pause the scrape, hand the challenge to a human, resume on signal.

    This is the *only* pattern that is simultaneously:
      - technically robust (humans always beat CAPTCHAs)
      - legally clean (a human solved it, not a script)
      - maintenance-free (no arms race)

    Returns True if the challenge element disappeared before timeout,
    False otherwise.

    Implementation notes for scrapex integration:
      - The caller owns the Playwright `page`; scrapex just waits.
      - The screenshot is saved next to the working directory so the
        operator can view it locally or via a UI in a future iteration.
      - Resumption is detected by polling for the challenge selector's
        disappearance — cheap, correct, and works for every CAPTCHA
        vendor because we are not parsing the challenge itself.
    """
    shot = Path(screenshot_path)
    shot.parent.mkdir(parents=True, exist_ok=True)

    # Take a screenshot so a human (or a future UI) can see the challenge.
    try:
        await page.screenshot(path=str(shot))
        screenshot_ok = True
    except Exception as exc:  # noqa: BLE001 - probe tolerates driver errors
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

    # Poll for the challenge to disappear. The selector intentionally
    # targets the *family* of CAPTCHA containers; matching the exact
    # class is brittle by design.
    deadline = time.monotonic() + timeout_s
    challenge_selector = (
        "iframe[src*='turnstile'], iframe[src*='recaptcha'], "
        "iframe[src*='hcaptcha'], .cf-turnstile, .g-recaptcha, .h-captcha"
    )
    while time.monotonic() < deadline:
        try:
            still_there = await page.locator(challenge_selector).count()
        except Exception:
            still_there = 0
        if still_there == 0:
            print("[hitl] challenge element gone — resuming scrape.")
            return True
        await asyncio.sleep(poll_interval_s)

    print("[hitl] timeout: challenge still present after "
          f"{timeout_s:.0f}s.")
    return False


# --- Probe runner ---------------------------------------------------------

async def _main() -> None:
    print("=" * 70)
    print("Probe 1: paid-service wrapper API shape (no credits consumed)")
    print("=" * 70)
    print("This hits 2captcha /res.php with a deliberately fake task id")
    print("to verify the request shape. 2captcha returns an error JSON")
    print("without consuming credits.\n")
    try:
        result = _probe_request_shape_2captcha()
        print(f"URL      : {result['url']}")
        print(f"HTTP     : {result['status_code']}")
        print(f"Body     : {result['body']}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"network probe failed: {exc!r}\n")

    print("=" * 70)
    print("Probe 2: signature demo for `solve_captcha_via_service`")
    print("=" * 70)
    try:
        await solve_captcha_via_service(
            page=None,
            service="2captcha",
            api_key="PROBE",
            sitekey="3x00000000000000000000FF",
            pageurl="https://example.com/",
        )
    except NotImplementedError as exc:
        print(f"as expected → NotImplementedError: {exc}\n")

    print("=" * 70)
    print("Probe 3: human-in-the-loop signature demo (no real page)")
    print("=" * 70)
    # We don't open a real browser; we just demonstrate the API surface
    # and confirm the signature is callable. A real scrapex integration
    # would pass the Playwright page here.
    class _FakePage:
        async def screenshot(self, path: str) -> None:
            Path(path).write_bytes(b"FAKE-SCREENSHOT-BYTE\n")

        def locator(self, selector: str):  # noqa: ARG002
            class _Locator:
                async def count(self_inner) -> int:
                    return 0
            return _Locator()

    ok = await solve_captcha_human_in_loop(
        page=_FakePage(),
        screenshot_path="captcha-challenge.png",
        timeout_s=2.0,
        poll_interval_s=0.5,
    )
    print(f"hitl probe completed cleanly: {ok}\n")
    print("All probes complete. See landscape.md and README.md.")


if __name__ == "__main__":
    asyncio.run(_main())
