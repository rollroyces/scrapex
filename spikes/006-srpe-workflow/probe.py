"""Spike 006 — SRPE workflow via browser-use.

This is a probe to answer ONE question: can browser-use handle the
HK SRPE multi-step workflow end-to-end?

Design:
- ONE single LLM-driven task, exactly as the user described
- Real Playwright headless browser
- Real OpenAI model (gpt-4o, default for browser-use)
- Hard cap on iterations so we don't burn $50 on a failed probe
- Verbose step-by-step logging to see WHERE it gets stuck
- Verdict: PASS / FAIL / PARTIAL with explicit evidence

Honest expected: the T&C checkbox will probably be the hardest step.
Government sites flag checkbox-clicks as bot signals.

Usage:
    OPENAI_API_KEY=*** python spikes/006-srpe-workflow/probe.py

If the user has no API key, run with --mock to see the integration shape
without the LLM cost. --mock will not actually load the page.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROBE_START_URL = (
    "https://www.srpe.gov.hk/opip/disclaimer_newly_upload_sales_brochure_price_list"
)
PDF_OUTPUT_DIR = Path("spikes/006-srpe-workflow/downloads")

# Hard caps so a runaway agent doesn't bankrupt the user.
MAX_STEPS = 25           # browser-use steps before we give up
MAX_PDFS = 5             # we don't actually need 98; 5 is enough to prove
TIMEOUT_S = 300          # 5 minute wall clock


async def probe_real(api_key: str) -> int:
    """Real probe — requires OPENAI_API_KEY.

    Returns exit code:
      0 — full success
      1 — partial / hit a wall
      2 — fatal (couldn't even start)
    """
    from browser_use import Agent
    from browser_use.browser import BrowserProfile
    from browser_use.llm import ChatOpenAI

    PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    task = """\
Go to https://www.srpe.gov.hk/opip/disclaimer_newly_upload_sales_brochure_price_list

1. Check the 'I have read and understood' checkbox
2. Click the Continue button
3. On the next page, look for any filter or search to show only
   items uploaded in the last 7 days. If there is no such filter,
   capture the date column and identify items whose upload date is
   within the last 7 days.
4. For up to {max_pdfs} of those recently-updated items, click into
   each one, find the 'register of transactions' link, and download
   the PDF to the folder {pdf_dir}.
5. After each download, report the filename in your final summary.

Hard limits:
- Do NOT exceed {max_steps} browser actions total.
- Do NOT visit more than {max_pdfs} item detail pages.
- If you get stuck on a single page for more than 3 actions, skip
  that item and move on.
- If the page blocks you (CAPTCHA, 403, anti-bot screen), report
  the blocker and stop.
""".format(
        max_pdfs=MAX_PDFS, max_steps=MAX_STEPS, pdf_dir=PDF_OUTPUT_DIR.resolve()
    )

    print(f"[*] Real probe: {MAX_PDFS} PDFs, {MAX_STEPS} step cap, "
          f"{TIMEOUT_S}s timeout")
    print(f"[*] Output dir: {PDF_OUTPUT_DIR.resolve()}")
    print(f"[*] Task: {task[:200]}...")
    print()

    llm = ChatOpenAI(model="gpt-4o", api_key=api_key)
    browser = BrowserProfile(headless=True)

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser,
    )

    try:
        result = await asyncio.wait_for(
            agent.run(),
            timeout=TIMEOUT_S,
        )
        print()
        print("=" * 60)
        print("RESULT")
        print("=" * 60)
        print(result)
        print()
        # Verify PDF files were actually downloaded
        pdfs = list(PDF_OUTPUT_DIR.glob("*.pdf"))
        print(f"PDFs on disk: {len(pdfs)}")
        for p in pdfs:
            print(f"  {p.name} ({p.stat().st_size} bytes)")
        return 0 if pdfs else 1
    except asyncio.TimeoutError:
        print(f"[!] TIMEOUT after {TIMEOUT_S}s")
        return 1
    except Exception as e:
        print(f"[!] FATAL: {type(e).__name__}: {e}")
        return 2


async def probe_mock() -> int:
    """Mock probe — no API key required.

    Just verifies the integration shape: imports, instantiates, builds
    the agent object. Does NOT actually run the browser.
    """
    print("[*] Mock probe — integration shape only, no browser")
    print()
    try:
        from browser_use import Agent
        from browser_use.browser import BrowserProfile
        from browser_use.llm import ChatOpenAI

        print(f"[+] import browser_use.Agent: OK")
        print(f"[+] import browser_use.llm.ChatOpenAI: OK")
        print(f"[+] import browser_use.browser.BrowserProfile: OK")

        # Build the agent object but don't run it
        llm = ChatOpenAI(model="gpt-4o")  # No api_key — will fail at call time
        browser = BrowserProfile(headless=True)
        task = "(mock task)"
        agent = Agent(task=task, llm=llm, browser_profile=browser)
        print(f"[+] Agent constructed: OK")
        print(f"[+] Task length: {len(task)} chars")
        print()
        print("Mock verdict: integration shape works. Real probe needs API key.")
        print("Run: OPENAI_API_KEY=*** python spikes/006-srpe-workflow/probe.py")
        return 0
    except Exception as e:
        print(f"[!] Mock probe failed at integration: {type(e).__name__}: {e}")
        return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run mock probe (no API key, no browser). Default: real.",
    )
    args = parser.parse_args()

    if args.mock:
        return asyncio.run(probe_mock())

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[!] OPENAI_API_KEY not set. Run with --mock to skip the LLM call.")
        return 2

    return asyncio.run(probe_real(api_key))


if __name__ == "__main__":
    sys.exit(main())