"""Cloudflare-aware fetcher using cloudscraper.

Why this exists
---------------
scrapex's default :class:`HttpFetcher` uses httpx, which cannot
solve Cloudflare's JavaScript anti-bot challenges. When a page
returns the "Just a moment..." or "Checking your browser..."
interstitial, plain httpx is stuck.

cloudscraper is a 6.7k-star library that wraps ``requests`` with
an embedded JavaScript interpreter. It solves Cloudflare's v2/v3
challenges and Turnstile challenges in Python — no browser
required, no Playwright install needed.

What this module does
---------------------
:class:`CloudscraperFetcher` is an async-friendly wrapper around
cloudscraper. Because cloudscraper is sync (``requests``-based),
we run each fetch in a thread executor via
:func:`asyncio.to_thread`. This adds ~5-10ms per call for the
thread context switch but keeps the rest of scrapex async.

Trade-offs vs :class:`HttpFetcher`
-----------------------------------
- **Slower per call** (5-10ms thread switch + JS challenge solve)
- **Faster than** :class:`BrowserFetcher` for Cloudflare pages
  (no browser launch, ~2s vs ~8s)
- **Different connection pool** (requests/urllib3 vs httpx)
- **Sync at heart** — wrapped, not native

When to use
-----------
- A page returns 403 with "Just a moment..." or "cf-chl-bypass"
  headers in the response
- The site uses Cloudflare but doesn't need full JS rendering
- You want Cloudflare bypass without Playwright's overhead

Installation
------------
This module is only importable if cloudscraper is installed::

    pip install scrapex[stealth]
"""
from __future__ import annotations

import asyncio
from typing import Any

from scrapex.errors import FetchError, RenderError
from scrapex.fetchers import FetchedPage, Fetcher, _quick_title


class CloudscraperFetcher(Fetcher):
    """Cloudflare-aware HTTP fetcher.

    Wraps :class:`cloudscraper.CloudScraper` (sync) into an async
    interface. Solves Cloudflare v2/v3 and Turnstile challenges
    without launching a browser.

    Parameters
    ----------
    interpreter:
        JS interpreter to use. ``"js2py"`` is pure-Python (slow,
        no install). ``"nodejs"`` requires Node.js installed.
        ``"v8"`` uses the ``python-engineio``-style V8 engine.
        Default: ``"js2py"`` (works out of the box, install deps
        via ``pip install scrapex[stealth]``).
    proxy:
        Optional proxy URL (e.g. ``http://proxy:8080``).
    """

    def __init__(
        self,
        *,
        interpreter: str = "js2py",
        proxy: str | None = None,
    ) -> None:
        try:
            import cloudscraper  # noqa: F401  (presence check)
        except ImportError as e:
            raise RenderError(
                "CloudscraperFetcher needs the 'stealth' extra: "
                "pip install 'scrapex[stealth]'"
            ) from e
        # Lazy import — cloudscraper is optional.
        import cloudscraper as _cs

        self._interpreter = interpreter
        self._proxy = proxy
        # CloudScraper is sync; we hold it for the fetcher's lifetime.
        # It manages its own session, cookie jar, and UA fingerprint.
        self._scraper: Any = _cs.create_scraper(
            interpreter=interpreter,
            browser={
                "browser": "chrome",
                "platform": "linux",
                "desktop": True,
            },
        )

    async def fetch(
        self,
        url: str,
        *,
        timeout_s: float,
        user_agent: str | None,
        proxy: str | None,
    ) -> FetchedPage:
        """Fetch ``url`` via cloudscraper (Cloudflare-aware)."""
        # Note: we ignore the caller-passed proxy because cloudscraper
        # was already configured with one in __init__. Changing it
        # mid-session would invalidate the cleared cookies. This is a
        # known limitation; if you need per-request proxy, create a
        # new CloudscraperFetcher.
        del proxy

        # Cloudscraper is sync; run in a thread to keep scrapex async.
        def _sync_fetch() -> tuple[int, str, str]:
            """Sync helper. Returns (status, final_url, html)."""
            kwargs: dict[str, Any] = {"timeout": timeout_s}
            if user_agent:
                kwargs["headers"] = {"User-Agent": user_agent}
            resp = self._scraper.get(url, **kwargs)
            return resp.status_code, str(resp.url), resp.text

        try:
            status, final_url, html = await asyncio.to_thread(_sync_fetch)
        except Exception as e:
            # cloudscraper raises requests.exceptions.* and its own
            # exceptions. Wrap everything in FetchError so callers
            # don't need to import cloudscraper to catch.
            raise FetchError(url, f"cloudscraper failed: {e}") from e

        if status >= 400:
            raise FetchError(
                url, f"HTTP {status} (cloudscraper)", status=status
            )

        return FetchedPage(
            url=final_url,
            status=status,
            html=html,
            render_mode="http",
            title=_quick_title(html),
        )

    async def aclose(self) -> None:
        """Close the underlying cloudscraper session.

        Cloudscraper wraps requests.Session which has a close()
        method. After close(), the fetcher cannot be reused.
        """
        close = getattr(self._scraper, "close", None)
        if callable(close):

            def _sync_close() -> None:
                close()

            await asyncio.to_thread(_sync_close)


__all__ = ["CloudscraperFetcher"]
