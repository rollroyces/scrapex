"""Session class — persists cookies across multiple ``scrape()`` calls.

This is the contrib-tier answer to "I need to authenticate once and
scrape 50 pages with the same session." It earns its keep by being
the natural extension of :func:`scrapex.scrape` — it returns the same
:class:`scrapex.ScrapeResult`, just with a persistent cookie jar.

Why this is contrib-tier (not core):
- The same job can be done with ``httpx.AsyncClient(cookies=...)`` plus
  a loop. The Session class is a thin convenience over that pattern.
- Cookies are credentials. We add explicit safety (sensitive-name
  guard, value-free list()) but the security baseline is that the
  user is responsible for where the cookie value comes from.
- Default state is "no jar, no leak surface" — you have to opt in
  to even have a session.

What is intentionally NOT here:
- No disk persistence (security baseline; the user can wrap if they
  want encrypted storage).
- No cookie encryption. Out of scope; the user can layer on top.
- No ``__repr__`` magic redaction. We just don't print cookies. We
  don't lie about what ``repr(session.cookies)`` shows.
- No browser-side cookies. Playwright owns its own cookie context.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Any

import httpx

from scrapex.errors import FetchError
from scrapex.extractors import get as get_extractor
from scrapex.models import (
    ExtractionStrategy,
    ScrapeRequest,
    ScrapeResult,
)
from scrapex.processing import html_to_markdown

# Cookie NAMES that strongly suggest the value is a credential.
# The value is NEVER included in any message derived from a name match.
_SENSITIVE_NAME_RE = re.compile(
    r"(session|auth|token|csrf|xsrf|sid|password|secret|api[_-]?key)",
    re.IGNORECASE,
)

# The only format string allowed for cookie logging — by design, no value.
_COOKIE_NAME_ONLY_FMT = "cookie(name=%r, sensitive=%s)"


def _is_sensitive(name: str) -> bool:
    """Return True if the cookie name suggests it holds a credential."""
    return bool(_SENSITIVE_NAME_RE.search(name))


@dataclass(slots=True)
class _CookieView:
    """A read-only, value-free snapshot of one cookie. Safe to log.

    The contract is that the value is never reachable through this type.
    If you need the value, use :attr:`Session.cookies` (the underlying
    ``httpx.Cookies``) — and accept that you are now in "I'm handling
    a credential" territory.
    """

    name: str
    domain: str
    path: str
    expires: float | None  # unix ts; None = session cookie

    def __repr__(self) -> str:  # part of the contract
        return _COOKIE_NAME_ONLY_FMT % (self.name, _is_sensitive(self.name))


class Session:
    """Persists cookies across multiple :func:`scrapex.scrape` calls.

    Holds one ``httpx.AsyncClient``. Cookies set by the server
    (``Set-Cookie``) on one ``scrape()`` are automatically attached to
    subsequent ``scrape()`` calls.

    Sensitive cookies (whose names match :data:`_SENSITIVE_NAME_RE`)
    must be set with ``sensitive=True``; otherwise a :class:`UserWarning`
    is emitted. The value is never included in the warning, in
    tracebacks, or in :func:`__repr__`.

    Example:
    -------
    >>> import asyncio
    >>> from scrapex import ScrapeRequest, FieldSpec, Schema, ExtractionStrategy
    >>> from scrapex.contrib.sessions import Session
    >>> async def main():
    ...     async with Session() as s:
    ...         await s.scrape("https://example.com/login")  # sets session cookie
    ...         # All subsequent scrape() calls reuse the same cookie jar.
    ...         result = await s.scrape(ScrapeRequest(
    ...             url="https://example.com/dashboard",
    ...             schema=Schema(
    ...                 strategy=ExtractionStrategy.CSS,
    ...                 fields=[FieldSpec(name="title", selector="h1")],
    ...             ),
    ...         ))
    ...         print(result.extracted)
    >>> asyncio.run(main())
    """

    def __init__(
        self,
        *,
        cookies: httpx.Cookies | dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 30.0,
        proxy: str | None = None,
        follow_redirects: bool = True,
    ) -> None:
        transport = httpx.AsyncHTTPTransport(proxy=proxy) if proxy else None
        self._client = httpx.AsyncClient(
            headers=headers or {},
            timeout=timeout_s,
            follow_redirects=follow_redirects,
            transport=transport,
        )
        if isinstance(cookies, dict):
            for k, v in cookies.items():
                self._client.cookies.set(k, v)
        # Public cookie jar (raw httpx.Cookies). Users can inspect, mutate,
        # or replace. The user owns credentials — we just hold them.
        self.cookies: httpx.Cookies = self._client.cookies

    async def aclose(self) -> None:
        """Close the underlying httpx client. Releases the connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> Session:
        """Return self for use as an async context manager."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Close the session on context exit."""
        await self.aclose()

    def set(
        self,
        name: str,
        value: str,
        *,
        domain: str = "",
        path: str = "/",
        sensitive: bool = False,
    ) -> None:
        """Set a cookie programmatically.

        Sensitive names (session, auth, token, csrf, xsrf, sid, password,
        secret, api_key) require ``sensitive=True``; otherwise a
        :class:`UserWarning` is emitted. The warning text contains
        the cookie name only — never the value.
        """
        if _is_sensitive(name) and not sensitive:
            warnings.warn(
                "setting a cookie whose name looks sensitive; if this is "
                "intentional, pass sensitive=True. " + (_COOKIE_NAME_ONLY_FMT % (name, True)),
                UserWarning,
                stacklevel=2,
            )
        self.cookies.set(name, value, domain=domain, path=path)

    def clear(self) -> None:
        """Wipe the cookie jar. The session is then equivalent to a fresh one."""
        self.cookies.clear()

    def list(self, *, domain: str | None = None) -> list[_CookieView]:
        """Return a value-free snapshot of the cookie jar.

        Safe to log. Each entry exposes only name, domain, path, and
        expiry — never the value.
        """
        out: list[_CookieView] = []
        for c in self.cookies.jar:
            d = c.domain.lstrip(".") or ""
            if domain is not None and d != domain.lstrip("."):
                continue
            out.append(_CookieView(name=c.name, domain=d, path=c.path, expires=c.expires))
        return out

    async def scrape(self, request: ScrapeRequest | dict[str, Any] | str) -> ScrapeResult:
        """Fetch + extract using this session's cookie jar.

        The fetch goes through the session's shared ``httpx`` client so
        ``Set-Cookie`` lands in our jar. Extraction is delegated to
        scrapex's pipeline; the result is identical to :func:`scrapex.scrape`
        for the same request, except the request went through the
        session's authenticated client.

        Parameters
        ----------
        request:
            Same shape as :func:`scrapex.scrape` accepts: a
            :class:`ScrapeRequest`, a dict, or a URL string.

        Returns:
        -------
        ScrapeResult
            Identical schema to :func:`scrapex.scrape`.

        Raises:
        ------
        FetchError:
            On transport failure or HTTP 4xx/5xx response.
        """
        if isinstance(request, str):
            req = ScrapeRequest(url=request)  # type: ignore[arg-type]
        elif isinstance(request, dict):
            req = ScrapeRequest(**request)
        else:
            req = request

        try:
            resp = await self._client.get(
                str(req.url),
                timeout=req.timeout_s,
                headers=({"User-Agent": req.user_agent} if req.user_agent else None),
            )
        except httpx.HTTPError as e:
            raise FetchError(str(req.url), f"transport error: {e}") from e

        if resp.status_code >= 400:
            raise FetchError(
                str(req.url),
                f"HTTP {resp.status_code}",
                status=resp.status_code,
            )

        return await _extract_only(resp.text, req, str(resp.url), resp.status_code)


async def _extract_only(html: str, req: ScrapeRequest, final_url: str, status: int) -> ScrapeResult:
    """Run scrapex's extraction stage on already-fetched HTML.

    Extracted to avoid duplicating the orchestrator's logic. The behavior
    matches :func:`scrapex.scrape` for the equivalent request, modulo
    the fetch step (already done) and the LLM branch (not exercised
    here — Session is a contrib addition; LLM extraction is core's job).
    """
    md = html_to_markdown(html, max_chars=req.markdown_max_chars) if req.include_markdown else None
    extracted: dict[str, Any] = {}
    warnings_: list[str] = []
    if req.schema_ is not None:
        if req.schema_.strategy == ExtractionStrategy.LLM:
            # LLM extraction requires the real orchestrator (config,
            # presets, env-var discovery). Surface a clear signal rather
            # than trying to half-implement it here.
            for f in req.schema_.fields:
                extracted[f.name] = None
            warnings_.append(
                "Session.scrape() does not run LLM extraction; "
                "use scrapex.scrape() for LLM extraction, or "
                "scrapex.contrib.sessions.Session with a CSS schema."
            )
        else:
            extractor = get_extractor(req.schema_.strategy.value)
            extracted = await extractor.extract(html, req.schema_)
        for f in req.schema_.fields:
            if f.required and not extracted.get(f.name):
                warnings_.append(f"required field '{f.name}' was not found")
    return ScrapeResult(
        url=str(req.url),
        final_url=final_url,
        status=status,
        markdown=md,
        html=html if not req.include_markdown else None,
        extracted=extracted,
        extraction_warnings=warnings_,
        render_mode_used="http",
        elapsed_ms=0,
    )


__all__ = ["Session"]
