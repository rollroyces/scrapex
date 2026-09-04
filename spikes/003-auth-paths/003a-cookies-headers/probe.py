"""Spike 003a — verify that adding a `headers` field to ScrapeRequest
makes cookie/header-based auth work.
"""
from __future__ import annotations

import asyncio

from aiohttp import web

from scrapex import ScrapeRequest, scrape
from scrapex.errors import FetchError


_SERVER_PORT: int | None = None


async def _protected_handler(request: web.Request) -> web.Response:
    if request.cookies.get("session") != "secret-123":
        return web.Response(status=401, text="unauthorized")
    return web.json_response({"secret": "you got in", "user_id": 42})


async def _bearer_handler(request: web.Request) -> web.Response:
    auth = request.headers.get("Authorization")
    if auth != "Bearer my-token":
        return web.Response(status=401, text="unauthorized")
    return web.json_response({"secret": "bearer works"})


async def start_server(handler) -> web.AppRunner:
    global _SERVER_PORT
    app = web.Application()
    app.router.add_get("/protected", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    if server is not None and server.sockets:  # type: ignore[attr-defined]
        _SERVER_PORT = server.sockets[0].getsockname()[1]
    return runner


def base_url() -> str:
    if _SERVER_PORT is None:
        raise RuntimeError("Server not started")
    return f"http://127.0.0.1:{_SERVER_PORT}/protected"


async def try_with(label: str, **kwargs) -> None:
    print(f"\n=== {label} ===")
    try:
        r = await scrape(ScrapeRequest(url=base_url(), **kwargs))
        print(f"  status={r.status}")
        if r.status == 200:
            print("  PASS")
        else:
            print("  status not 200 (auth likely missing)")
    except Exception as e:
        print(f"  REJECTED: {type(e).__name__}: {str(e)[:200]}")


async def main() -> None:
    print("=" * 60)
    print("Spike 003a — Cookie/header injection")
    print("=" * 60)

    # Phase 1: cookie-based auth
    print("\n--- Phase 1: cookie auth (session=secret-123) ---")
    runner = await start_server(_protected_handler)
    try:
        await try_with("Without cookie (current behavior — should 401)")
        await try_with("With headers={'Cookie': '...'}", headers={"Cookie": "session=secret-123"})
        await try_with("With cookies={...}", cookies={"session": "secret-123"})
    finally:
        await runner.cleanup()

    # Phase 2: bearer auth
    print("\n--- Phase 2: bearer auth ---")
    runner = await start_server(_bearer_handler)
    try:
        await try_with(
            "With headers={'Authorization': 'Bearer ...'}",
            headers={"Authorization": "Bearer my-token"},
        )
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())