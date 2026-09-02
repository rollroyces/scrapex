"""Fetchers — turn a URL into raw HTML.

Two implementations: :class:`HttpFetcher` (httpx, fast) and
:class:`BrowserFetcher` (Playwright, runs JS). The :func:`choose_fetcher`
helper picks one based on the request's :class:`RenderMode` and the page
content.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from scrapex.errors import FetchError, RenderError


@dataclass(slots=True)
class FetchedPage:
    """The raw output of a fetcher — kept tiny on purpose."""

    url: str  # final URL after redirects
    status: int
    html: str
    render_mode: Literal["http", "browser"]
    title: str | None = None


class Fetcher(abc.ABC):
    """Abstract base. Implementations must be reusable across calls."""

    @abc.abstractmethod
    async def fetch(
        self, url: str, *, timeout_s: float, user_agent: str | None, proxy: str | None
    ) -> FetchedPage:
        """Fetch ``url`` and return the raw page. Implementations must be safe to call multiple times.

        Parameters
        ----------
        url:
            The URL to fetch.
        timeout_s:
            Timeout in seconds for the fetch.
        user_agent:
            Optional override for the User-Agent header.
        proxy:
            Optional proxy URL (e.g. ``http://proxy:8080``).
        """
        ...

    async def aclose(self) -> None:
        """Release any resources held by the fetcher (e.g. browser process).

        Default implementation is a no-op for stateless fetchers.
        """
        return None


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class HttpFetcher(Fetcher):
    """Plain HTTP fetch — fast, no JS execution."""

    def __init__(self, proxy: str | None = None) -> None:
        # httpx 0.28+ removed the per-request ``proxy`` kwarg; proxies are now
        # mounted on the client. ``AsyncHTTPTransport(proxy=...)`` is enough
        # for both http:// and https://.
        transport = httpx.AsyncHTTPTransport(proxy=proxy) if proxy else None
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            headers={"User-Agent": _DEFAULT_UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=30.0,
            transport=transport,
        )

    async def fetch(
        self,
        url: str,
        *,
        timeout_s: float,
        user_agent: str | None,
        proxy: str | None,
    ) -> FetchedPage:
        """Fetch the page over HTTP using httpx + HTTP/2.

        Returns a :class:`FetchedPage` on success. Raises
        :class:`~scrapex.FetchError` on any HTTP 4xx/5xx response or
        transport-level failure (DNS, TLS, timeout, connection refused).
        """
        headers: dict[str, str] = {}
        if user_agent:
            headers["User-Agent"] = user_agent
        try:
            r = await self._client.get(url, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise FetchError(url, f"timeout after {timeout_s}s") from e
        except httpx.HTTPError as e:
            raise FetchError(url, f"transport error: {e}") from e
        if r.status_code >= 400:
            raise FetchError(url, f"HTTP {r.status_code}", status=r.status_code)
        # Cheap title extraction — full extraction happens later
        title = _quick_title(r.text)
        return FetchedPage(
            url=str(r.url),
            status=r.status_code,
            html=r.text,
            render_mode="http",
            title=title,
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client and release its connection pool."""
        await self._client.aclose()


class BrowserFetcher(Fetcher):
    """Playwright-based fetch — runs JavaScript.

    Optional dependency: requires ``playwright`` to be installed
    (and ``playwright install chromium`` to have been run).
    """

    def __init__(self) -> None:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError as e:
            raise RenderError(
                "BrowserFetcher needs the 'browser' extra: "
                "pip install 'scrapex[browser]' && playwright install chromium"
            ) from e
        # Typed as Any because playwright is optional — mypy shouldn't
        # chase types it can't see when the dep isn't installed.
        self._playwright: Any = None
        self._browser: Any = None

    async def _ensure_browser(self, proxy: str | None) -> None:
        if self._browser is not None:
            return
        from playwright.async_api import (
            async_playwright,
        )

        self._playwright = await async_playwright().start()
        kwargs: dict[str, Any] = {"headless": True}
        if proxy:
            kwargs["proxy"] = {"server": proxy}
        self._browser = await self._playwright.chromium.launch(**kwargs)

    async def fetch(
        self,
        url: str,
        *,
        timeout_s: float,
        user_agent: str | None,
        proxy: str | None,
    ) -> FetchedPage:
        """Fetch the page using a real browser (Playwright + Chromium).

        Launches Chromium on first use; reuses it for subsequent fetches
        in the same instance. Use this when the page needs JavaScript
        execution to render content.

        Returns a :class:`FetchedPage` on success. Raises
        :class:`~scrapex.FetchError` on HTTP 4xx/5xx (from the final
        response) or :class:`~scrapex.RenderError` on browser crashes.
        """
        await self._ensure_browser(proxy)
        assert self._browser is not None
        ctx = await self._browser.new_context(
            user_agent=user_agent or _DEFAULT_UA,
            ignore_https_errors=True,
        )
        try:
            page = await ctx.new_page()
            response = await page.goto(url, timeout=timeout_s * 1000, wait_until="networkidle")
            status = response.status if response else 0
            html = await page.content()
            title = await page.title()
        except Exception as e:
            raise RenderError(f"playwright failed: {e}") from e
        finally:
            await ctx.close()
        if status >= 400:
            raise FetchError(url, f"HTTP {status} (browser)", status=status)
        return FetchedPage(
            url=url,
            status=status,
            html=html,
            render_mode="browser",
            title=title,
        )

    async def aclose(self) -> None:
        """Close the Chromium browser and stop the Playwright driver.

        Safe to call even if no fetch was ever attempted (both handles
        stay ``None`` in that case).
        """
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()


def _quick_title(html: str) -> str | None:
    """Pull ``<title>`` cheaply; full extraction later handles the rest."""
    import re

    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()[:500]


async def choose_fetcher(mode: str, *, proxy: str | None = None) -> Fetcher:
    """Pick a fetcher based on the request's :class:`RenderMode`."""
    if mode == "browser":
        return BrowserFetcher()
    return HttpFetcher(proxy=proxy)


# Public exports
__all__ = [
    "BrowserFetcher",
    "FetchedPage",
    "Fetcher",
    "HttpFetcher",
    "choose_fetcher",
]
