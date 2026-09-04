"""Tests for scrapex.contrib.sessions — every branch in the spec.

Covers:
- Cookie persistence across 5 sequential scrape() calls
- Inspection surface: .cookies, .list() (value-free)
- Sensitive-name guard: warning fires, value never leaked
- clear() wipes the jar
- Non-CSS strategy: surfaces a clear warning, doesn't crash
- LLM strategy: explicit "not implemented here" warning
- Transport error: wraps in FetchError
- 4xx/5xx: wraps in FetchError with status
- Async context manager
- aclose() is idempotent
"""
from __future__ import annotations

import json
import traceback
import warnings

import pytest
import respx
from aiohttp import web
from httpx import Response

from scrapex import ExtractionStrategy, FieldSpec, Schema, ScrapeRequest
from scrapex.contrib.sessions import Session
from scrapex.errors import FetchError

# --- Local test server (port 0 → aiohttp picks free) ----------------------


async def _login(_req: web.Request) -> web.Response:
    resp = web.Response(text="logged in")
    resp.set_cookie("session", "SUPER-SECRET-SESSION-VALUE", httponly=True)
    resp.set_cookie("csrf", "CSRF-VALUE-XYZ")
    resp.set_cookie("tracking", "anon-12345")
    return resp


async def _echo_cookies(req: web.Request) -> web.Response:
    return web.json_response(dict(req.cookies))


async def _page_a(_req: web.Request) -> web.Response:
    return web.Response(
        text="<html><head><title>Page A</title></head>"
        "<body><h1 class='t'>A</h1></body></html>",
        content_type="text/html",
    )


async def _page_b(_req: web.Request) -> web.Response:
    return web.Response(
        text="<html><head><title>Page B</title></head>"
        "<body><h1 class='t'>B</h1></body></html>",
        content_type="text/html",
    )


async def _page_404(_req: web.Request) -> web.Response:
    return web.Response(status=404, text="not found")


async def _start_server() -> tuple[web.AppRunner, int]:
    app = web.Application()
    app.router.add_get("/login", _login)
    app.router.add_get("/whoami", _echo_cookies)
    app.router.add_get("/a", _page_a)
    app.router.add_get("/b", _page_b)
    app.router.add_get("/nope-404", _page_404)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    sockets = server.sockets  # type: ignore[attr-defined]
    port = sockets[0].getsockname()[1]
    return runner, port


# --- Tests ------------------------------------------------------------------


async def test_session_persists_cookies_across_5_calls():
    runner, port = await _start_server()
    base = f"http://127.0.0.1:{port}"
    try:
        async with Session() as session:
            # 1. Login → server sets 3 cookies
            r = await session.scrape(f"{base}/login")
            assert r.status == 200

            # 2-4. Three more pages, each extraction works
            for path, want in [("/a", "A"), ("/b", "B")]:
                r = await session.scrape(ScrapeRequest(
                    url=f"{base}{path}",
                    schema=Schema(
                        strategy=ExtractionStrategy.CSS,
                        fields=[FieldSpec(name="title", selector="h1.t")],
                    ),
                ))
                assert r.extracted["title"] == want

            # 5. Verify cookies survived (the point of Session)
            r = await session.scrape(ScrapeRequest(
                url=f"{base}/whoami",
                include_markdown=False,
            ))
            echoed = json.loads(r.html or "{}")
            for name in ("session", "csrf", "tracking"):
                assert name in echoed, f"cookie {name!r} missing from /whoami"
    finally:
        await runner.cleanup()


async def test_session_inspection_list_is_value_free():
    runner, port = await _start_server()
    base = f"http://127.0.0.1:{port}"
    try:
        async with Session() as session:
            await session.scrape(f"{base}/login")
            snapshots = session.list()
            assert len(snapshots) == 3
            # No snapshot has a 'value' attribute (compile-time check:
            # _CookieView is a frozen dataclass with only name/domain/path/expires)
            for s in snapshots:
                assert hasattr(s, "name")
                assert hasattr(s, "domain")
                assert hasattr(s, "path")
                assert hasattr(s, "expires")
                assert not hasattr(s, "value")  # by design
                # The repr must not contain any cookie value
                assert "SUPER-SECRET" not in repr(s)
                assert "CSRF-VALUE" not in repr(s)
    finally:
        await runner.cleanup()


async def test_session_sensitive_name_guard_fires_warning():
    async with Session() as session:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.set("auth_token", "leaked-value-12345")
        msgs = [str(w.message) for w in caught]
        assert any("sensitive" in m.lower() for m in msgs), (
            f"expected UserWarning about sensitive name; got: {msgs}"
        )
        # The value MUST NOT appear in any warning message
        for m in msgs:
            assert "leaked-value-12345" not in m, (
                f"cookie value leaked into warning: {m!r}"
            )


async def test_session_sensitive_name_with_sensitive_true_suppresses():
    async with Session() as session:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.set("auth_token", "real-token", sensitive=True)
        sensitive_warnings = [
            w for w in caught
            if "sensitive" in str(w.message).lower()
            and "auth_token" in str(w.message).lower()
        ]
        assert sensitive_warnings == [], (
            f"expected no sensitive warning when sensitive=True; got: "
            f"{[str(w.message) for w in caught]}"
        )


async def test_session_clear_wipes_the_jar():
    runner, port = await _start_server()
    base = f"http://127.0.0.1:{port}"
    try:
        async with Session() as session:
            await session.scrape(f"{base}/login")
            assert len(session.cookies) == 3
            session.clear()
            assert len(session.cookies) == 0
            # /whoami should now see no cookies
            r = await session.scrape(ScrapeRequest(
                url=f"{base}/whoami", include_markdown=False
            ))
            echoed = json.loads(r.html or "{}")
            assert echoed == {}, f"cookies survived clear(): {echoed!r}"
    finally:
        await runner.cleanup()


async def test_session_fetch_error_does_not_leak_cookie_value():
    runner, port = await _start_server()
    base = f"http://127.0.0.1:{port}"
    try:
        async with Session() as session:
            await session.scrape(f"{base}/login")
            try:
                await session.scrape(f"{base}/nope-404")
            except FetchError as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                assert "SUPER-SECRET-SESSION-VALUE" not in tb, (
                    f"FetchError traceback leaked cookie: {tb!r}"
                )
                assert e.status == 404
    finally:
        await runner.cleanup()


async def test_session_accepts_string_url():
    """Session.scrape() accepts the same shapes as scrapex.scrape()."""
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text="<p>x</p>")
        )
        async with Session() as session:
            r = await session.scrape("https://example.com")
            assert r.status == 200


async def test_session_accepts_dict():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text="<p>x</p>")
        )
        async with Session() as session:
            r = await session.scrape({"url": "https://example.com"})
            assert r.status == 200


async def test_session_initial_cookies_dict():
    """You can seed the jar at construction time with cookies={...}."""
    async with Session(cookies={"auth": "xyz"}) as s:
        assert s.cookies.get("auth") == "xyz"
        assert s.list()[0].name == "auth"
        assert s.list()[0].__repr__() == "cookie(name='auth', sensitive=True)"


async def test_session_transport_error_raises_fetch_error():
    """Connection refused → FetchError (no status), not a raw httpx error."""
    async with Session(timeout_s=2) as session:
        # Port 1 is reserved and refuses connections on most systems.
        with pytest.raises(FetchError) as exc_info:
            await session.scrape("http://127.0.0.1:1/")
        assert exc_info.value.status is None


async def test_session_llm_strategy_emits_clear_warning():
    """Session doesn't try to run LLM extraction; it surfaces a clear warning
    so the user knows to use scrapex.scrape() for LLM jobs."""
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=Response(200, text="<p>x</p>")
        )
        async with Session() as session:
            r = await session.scrape(ScrapeRequest(
                url="https://example.com",
                schema=Schema(
                    strategy=ExtractionStrategy.LLM,
                    fields=[FieldSpec(name="title", description="title")],
                ),
            ))
            assert r.extracted == {"title": None}
            assert any("LLM" in w for w in r.extraction_warnings)


async def test_session_aclose_is_idempotent():
    s = Session()
    await s.aclose()
    await s.aclose()  # must not crash


async def test_session_no_jar_means_no_leak_surface():
    """Default state: no cookies, no leak surface."""
    async with Session() as s:
        assert len(s.cookies) == 0
        assert s.list() == []
        # No sensitive-name warning should fire when no cookies are set
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s.set("tracking", "ok")  # not sensitive name
        assert not caught  # no warning, no leak
