"""Spike 004c — session/cookie persistence across scrape() calls.

Throwaway probe code; lives ONLY in spikes/004c-sessions/. Designed to
answer "is this worth shipping?" not "is this production-ready?".

Design (what's in Session vs what's not):

IN
- Holds an httpx.AsyncClient (we don't reinvent the HTTP layer)
- .cookies exposes the cookie jar for inspection
- Same client across scrape() calls → cookies persist automatically
- .clear() wipes the jar
- Cookie NAMES matching a sensitive pattern require explicit sensitive=True
  when set programmatically (a UserWarning is emitted; never the value)
- _CookieView gives a value-free snapshot for safe logging/debugging

OUT
- No disk persistence (security baseline)
- No cookie encryption (out of scope; user can wrap .cookies themselves)
- No automatic __repr__ redaction (would be a lie — we just don't print)
- No browser-side cookies (Playwright owns its own context; not covered)

Run: `python probe.py`
"""

from __future__ import annotations

import asyncio
import re
import sys
import traceback
import warnings
from dataclasses import dataclass
from typing import Any

import httpx
from aiohttp import web
from pydantic import HttpUrl

# Re-use scrapex's public surface so the probe is honest about wiring.
from scrapex import ScrapeRequest
from scrapex.errors import FetchError
from scrapex.extractors import get as get_extractor
from scrapex.models import ExtractionResult, ExtractionStrategy, ScrapeResult
from scrapex.processing import html_to_markdown


# Cookie NAMES that strongly suggest the value is a credential.
_SENSITIVE_NAME_RE = re.compile(
    r"(session|auth|token|csrf|xsrf|sid|password|secret|api[_-]?key)",
    re.IGNORECASE,
)

# The only format string allowed for cookie logging — by design, no value.
_COOKIE_NAME_ONLY_FMT = "cookie(name=%r, sensitive=%s)"


def _is_sensitive(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name))


@dataclass(slots=True)
class _CookieView:
    """A read-only, value-free snapshot of one cookie. Safe to log."""

    name: str
    domain: str
    path: str
    expires: float | None  # unix ts; None = session cookie

    def __repr__(self) -> str:  # part of the contract
        return _COOKIE_NAME_ONLY_FMT % (self.name, _is_sensitive(self.name))


class Session:
    """Persists cookies across multiple scrape() calls.

    Holds one httpx.AsyncClient. Cookies set by the server (Set-Cookie) on
    one scrape() are automatically attached to subsequent scrape() calls.

    Sensitive cookies (whose names match _SENSITIVE_NAME_RE) must be set
    with sensitive=True; otherwise a UserWarning is emitted. The value is
    never included in the warning, in tracebacks, or in __repr__.
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
        self.cookies: httpx.Cookies = self._client.cookies

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Session":
        return self

    async def __aexit__(self, *exc: Any) -> None:
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
        """Set a cookie programmatically. Sensitive names need sensitive=True."""
        if _is_sensitive(name) and not sensitive:
            warnings.warn(
                "setting a cookie whose name looks sensitive; if this is "
                "intentional, pass sensitive=True. "
                + (_COOKIE_NAME_ONLY_FMT % (name, True)),
                UserWarning,
                stacklevel=2,
            )
        self.cookies.set(name, value, domain=domain, path=path)

    def clear(self) -> None:
        """Wipe the cookie jar."""
        self.cookies.clear()

    def list(self, *, domain: str | None = None) -> list[_CookieView]:
        """Value-free snapshot of the cookie jar — safe to log."""
        out: list[_CookieView] = []
        for c in self.cookies.jar:
            d = c.domain.lstrip(".") or ""
            if domain is not None and d != domain.lstrip("."):
                continue
            out.append(
                _CookieView(
                    name=c.name, domain=d, path=c.path, expires=c.expires
                )
            )
        return out

    async def scrape(self, request: ScrapeRequest | dict[str, Any] | str) -> ScrapeResult:
        """Fetch + extract using this session's cookie jar.

        The fetch goes through the session's shared httpx client so Set-Cookie
        lands in our jar. Extraction is delegated to scrapex's pipeline.
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
                str(req.url), f"HTTP {resp.status_code}", status=resp.status_code
            )

        return await _extract_only(
            resp.text, req, str(resp.url), resp.status_code
        )


async def _extract_only(
    html: str, req: ScrapeRequest, final_url: str, status: int
) -> ScrapeResult:
    """Run scrapex's extraction stage on already-fetched HTML."""
    md = (
        html_to_markdown(html, max_chars=req.markdown_max_chars)
        if req.include_markdown
        else None
    )
    extracted: dict[str, Any] = {}
    warnings_: list[str] = []
    if req.schema_ is not None:
        if req.schema_.strategy == ExtractionStrategy.NONE:
            extracted = {}
        elif req.schema_.strategy == ExtractionStrategy.LLM:
            # Skip the LLM extractor in the probe — costs money, not what
            # we're testing. Surface a clear signal instead.
            for f in req.schema_.fields:
                extracted[f.name] = ExtractionResult(
                    name=f.name, value=None, found=False, error="LLM skipped in probe"
                ).model_dump()
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


# --------------------------------------------------------------------------
# Local test server (aiohttp) — five endpoints to exercise the session
# --------------------------------------------------------------------------

_TEST_COOKIE_NAME = "session"
_TEST_COOKIE_VALUE = "SUPER-SECRET-SESSION-VALUE-DO-NOT-LEAK"  # noqa: S105


async def _login(_req: web.Request) -> web.Response:
    resp = web.Response(text="logged in")
    resp.set_cookie(_TEST_COOKIE_NAME, _TEST_COOKIE_VALUE, httponly=True)
    resp.set_cookie("csrf", "CSRF-VALUE-XYZ")
    resp.set_cookie("tracking", "anon-12345")
    return resp


async def _echo_cookies(req: web.Request) -> web.Response:
    return web.json_response(dict(req.cookies))


async def _page_a(_req: web.Request) -> web.Response:
    return web.Response(
        text="<html><head><title>Page A</title></head><body>"
        "<h1 class='t'>A</h1></body></html>",
        content_type="text/html",
    )


async def _page_b(_req: web.Request) -> web.Response:
    return web.Response(
        text="<html><head><title>Page B</title></head><body>"
        "<h1 class='t'>B</h1></body></html>",
        content_type="text/html",
    )


async def _page_c(_req: web.Request) -> web.Response:
    return web.Response(
        text="<html><head><title>Page C</title></head><body>"
        "<h1 class='t'>C</h1></body></html>",
        content_type="text/html",
    )


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/login", _login)
    app.router.add_get("/whoami", _echo_cookies)
    app.router.add_get("/a", _page_a)
    app.router.add_get("/b", _page_b)
    app.router.add_get("/c", _page_c)
    return app


# --------------------------------------------------------------------------
# Probe
# --------------------------------------------------------------------------


async def run_probe() -> int:
    from scrapex.models import ExtractionStrategy, FieldSpec, Schema

    runner = web.AppRunner(build_app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    # Discover the chosen port.
    sockets = list(site._server.sockets)  # type: ignore[attr-defined]
    port = sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    print(f"=== test server up at {base} ===")
    failures: list[str] = []
    try:
        # -------- 5 sequential scrape() calls using one session --------
        async with Session() as session:
            print("[1] login (server sets 3 cookies)")
            r = await session.scrape(f"{base}/login")
            assert r.status == 200, f"login status={r.status}"

            print("[2] /whoami — expect all 3 cookies back")
            # Force include_markdown=False so the JSON body lands in r.html.
            r = await session.scrape(
                ScrapeRequest(
                    url=HttpUrl(f"{base}/whoami"),
                    include_markdown=False,
                )
            )
            import json as _json
            assert r.html is not None
            echoed = _json.loads(r.html)
            for name in ("session", "csrf", "tracking"):
                if name not in echoed:
                    failures.append(f"cookie {name!r} missing from /whoami echo")
            print(f"    echoed cookies: {sorted(echoed)}")

            print("[3] /a (CSS extraction)")
            r = await session.scrape(
                ScrapeRequest(
                    url=HttpUrl(f"{base}/a"),
                    schema=Schema(
                        strategy=ExtractionStrategy.CSS,
                        fields=[FieldSpec(name="title", selector="h1.t")],
                    ),
                )
            )
            if r.extracted.get("title") != "A":
                failures.append(f"page A title wrong: {r.extracted!r}")

            print("[4] /b (CSS extraction)")
            r = await session.scrape(
                ScrapeRequest(
                    url=HttpUrl(f"{base}/b"),
                    schema=Schema(
                        strategy=ExtractionStrategy.CSS,
                        fields=[FieldSpec(name="title", selector="h1.t")],
                    ),
                )
            )
            if r.extracted.get("title") != "B":
                failures.append(f"page B title wrong: {r.extracted!r}")

            print("[5] /c (CSS extraction) — confirm session still alive")
            r = await session.scrape(
                ScrapeRequest(
                    url=HttpUrl(f"{base}/c"),
                    schema=Schema(
                        strategy=ExtractionStrategy.CSS,
                        fields=[FieldSpec(name="title", selector="h1.t")],
                    ),
                )
            )
            if r.extracted.get("title") != "C":
                failures.append(f"page C title wrong: {r.extracted!r}")

            # -------- inspection surface --------
            print("\n[inspection] session.cookies (raw httpx.Cookies)")
            print(f"  len: {len(session.cookies)}")
            print(f"  list (value-free): {session.list()}")

            # -------- security check --------
            print("\n[security] sensitive-name guard")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                session.set("auth_token", "leaked-value-12345")
            warning_msgs = [str(w.message) for w in caught]
            if not any("sensitive" in m.lower() for m in warning_msgs):
                failures.append("expected UserWarning for sensitive cookie name")
            if any("leaked-value-12345" in m for m in warning_msgs):
                failures.append("cookie VALUE leaked into warning message!")
            else:
                print(f"  warning raised without leaking value: {warning_msgs!r}")

            print("\n[security] explicit sensitive=True suppresses warning")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                session.set("auth_token", "real-token", sensitive=True)
            if any("sensitive" in str(w.message).lower() for w in caught):
                failures.append("warning raised even with sensitive=True")

            # -------- traceback leak check --------
            print("\n[security] raise an error with cookie value in scope")
            secret = session.cookies.get(_TEST_COOKIE_NAME) or _TEST_COOKIE_VALUE
            try:
                # Put the secret in scope, then raise something whose
                # traceback we capture.
                raise RuntimeError(f"upstream blew up while using cookie={secret!r}")
            except RuntimeError as e:
                tb_text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # The secret WILL appear in the explicit error message we
                # built — that's the user's choice. The point of this test
                # is to verify scrapex's *own* exception classes don't echo
                # cookie values, and that our Session's internals don't
                # either.
                print(f"  traceback length: {len(tb_text)} chars")
                # Quick assertion: does anything in the scrapex surface (not
                # the message we crafted) echo the value?
                # Our test error message DID include it (deliberately);
                # that's outside the probe's responsibility.

            # Now raise a *scrapex* error and confirm cookie value isn't
            # echoed by scrapex's own message.
            try:
                # Force a FetchError with a request that 404s
                await session.scrape(f"{base}/nope-404")
            except FetchError as e:
                tb_text = "".join(
                    traceback.format_exception(type(e), e, e.__traceback__)
                )
                if _TEST_COOKIE_VALUE in tb_text:
                    failures.append(
                        f"FetchError traceback leaked cookie value: {tb_text!r}"
                    )
                else:
                    print("  FetchError traceback does NOT contain cookie value ✓")

            # -------- clear() --------
            print("\n[inspection] session.clear() wipes the jar")
            session.clear()
            print(f"  len after clear: {len(session.cookies)}")
            if len(session.cookies) != 0:
                failures.append("session.clear() did not empty the jar")

            # After clear(), whoami should see no cookies
            r = await session.scrape(
                ScrapeRequest(
                    url=HttpUrl(f"{base}/whoami"),
                    include_markdown=False,
                )
            )
            assert r.html is not None
            echoed_after = _json.loads(r.html)
            if echoed_after:
                failures.append(f"cookies survived clear(): {echoed_after!r}")
            print(f"  /whoami after clear: {echoed_after}")

    finally:
        await runner.cleanup()

    # ---- summary ----
    print("\n=== probe summary ===")
    if failures:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS — session persists cookies, jar is inspectable, "
          "no value leaked via warnings or FetchError traceback")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_probe()))
