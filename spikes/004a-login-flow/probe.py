"""Spike 004a — login-flow automation.

Compares:
  Way A: raw Playwright (baseline)
  Way B: scrapex wrapper with a hypothetical BrowserSession (fluent + auto-extract)

Both implementations drive the SAME mock server defined below.
The verdict is computed by `count_loc` on the two function bodies.
"""

from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import dataclass
from typing import Any

from aiohttp import web

# ---------------------------------------------------------------------------
# Mock server: login form -> dashboard -> "download PDF" button
# ---------------------------------------------------------------------------


def make_mock_app() -> web.Application:
    app = web.Application()

    async def login_page(request: web.Request) -> web.Response:
        if request.method == "POST":
            data = await request.post()
            if data.get("user") == "alice" and data.get("pw") == "secret":
                resp = web.Response(text="ok", status=200)
                resp.set_cookie("session", "tok-123", httponly=True)
                resp.headers["Location"] = "/dashboard"
                resp.set_status(302)
                return resp
            return web.Response(text="bad", status=401)
        return web.Response(
            text=(
                "<html><body>"
                "<form method='POST' action='/login'>"
                "<input name='user' id='user'/>"
                "<input name='pw' id='pw' type='password'/>"
                "<button id='go'>Sign in</button>"
                "</form></body></html>"
            ),
            content_type="text/html",
        )

    async def dashboard(request: web.Request) -> web.Response:
        if request.cookies.get("session") != "tok-123":
            return web.HTTPFound("/login")
        return web.Response(
            text=(
                "<html><body>"
                "<h1 id='welcome'>Welcome alice</h1>"
                "<a id='pdf' href='/report.pdf'>Download PDF</a>"
                "</body></html>"
            ),
            content_type="text/html",
        )

    async def report(request: web.Request) -> web.Response:
        if request.cookies.get("session") != "tok-123":
            return web.HTTPForbidden()
        return web.Response(
            body=b"%PDF-1.4\n%fake report bytes\n%%EOF",
            content_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
        )

    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_page)
    app.router.add_get("/dashboard", dashboard)
    app.router.add_get("/report.pdf", report)
    return app


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Shared runner: start server, run a coroutine that performs the flow,
# return the captured result for assertion.
# ---------------------------------------------------------------------------


@dataclass
class FlowResult:
    welcome_text: str
    pdf_bytes: bytes
    pdf_size: int


async def run_in_server(flow_coro_factory) -> FlowResult:
    app = make_mock_app()
    port = pick_free_port()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        base = f"http://127.0.0.1:{port}"
        return await flow_coro_factory(base)
    finally:
        await runner.cleanup()


# ===========================================================================
# Way A — raw Playwright
# ===========================================================================


async def way_a_raw_playwright(base_url: str) -> FlowResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(f"{base_url}/login")
            await page.fill("#user", "alice")
            await page.fill("#pw", "secret")
            await page.click("#go")
            await page.wait_for_url("**/dashboard")
            welcome = await page.locator("#welcome").text_content()
            async with page.expect_download() as dl_info:
                await page.click("#pdf")
            download = await dl_info.value
            path = await download.path()
            with open(path, "rb") as f:
                data = f.read()
            return FlowResult(welcome_text=welcome or "", pdf_bytes=data, pdf_size=len(data))
        finally:
            await browser.close()


# ===========================================================================
# Way B — scrapex hypothetical wrapper
# ===========================================================================
#
# The wrapper is a fluent chain that:
#   - opens a browser (auto-managed context)
#   - logs in via form fill + submit (handles 302 + cookies)
#   - navigates + auto-extracts a CSS selector
#   - downloads a file via a CSS selector click + expects-download
# No playwright import surface visible to the caller.


class BrowserSession:
    """Hypothetical scrapex wrapper over Playwright for login + extraction flows."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless

    async def __aenter__(self) -> "BrowserSession":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        self._ctx = await self._browser.new_context()
        self._page = await self._ctx.new_page()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._browser.close()
        await self._pw.stop()

    async def goto(self, url: str) -> "BrowserSession":
        await self._page.goto(url)
        return self

    async def fill(self, selector: str, value: str) -> "BrowserSession":
        await self._page.fill(selector, value)
        return self

    async def submit(self, selector: str, wait_url: str) -> "BrowserSession":
        async with self._page.expect_navigation():
            await self._page.click(selector)
        await self._page.wait_for_url(f"**{wait_url}")
        return self

    async def text(self, selector: str) -> str:
        return (await self._page.locator(selector).text_content()) or ""

    async def download(self, selector: str) -> bytes:
        async with self._page.expect_download() as dl_info:
            await self._page.click(selector)
        download = await dl_info.value
        path = await download.path()
        with open(path, "rb") as f:
            return f.read()


async def way_b_scrapex(base_url: str) -> FlowResult:
    async with BrowserSession() as b:
        await b.goto(f"{base_url}/login")
        await b.fill("#user", "alice")
        await b.fill("#pw", "secret")
        await b.submit("#go", "/dashboard")
        welcome = await b.text("#welcome")
        pdf = await b.download("#pdf")
        return FlowResult(welcome_text=welcome, pdf_bytes=pdf, pdf_size=len(pdf))


# ===========================================================================
# LoC counting — non-blank, non-comment lines of each flow body.
# We strip docstrings/comments by parsing the AST of each function body.
# ===========================================================================


def count_loc(source: str, fn_name: str) -> int:
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
            lines = source.splitlines()
            body_lines = set()
            for stmt in node.body:
                body_lines.update(range(stmt.lineno, stmt.end_lineno + 1))
            count = 0
            for ln in body_lines:
                line = lines[ln - 1]
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    continue
                count += 1
            return count
    raise ValueError(f"function {fn_name} not found")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def main() -> None:
    res_a = await run_in_server(way_a_raw_playwright)
    res_b = await run_in_server(way_b_scrapex)
    assert res_a.welcome_text == "Welcome alice"
    assert res_b.welcome_text == "Welcome alice"
    assert res_a.pdf_bytes == b"%PDF-1.4\n%fake report bytes\n%%EOF"
    assert res_b.pdf_bytes == b"%PDF-1.4\n%fake report bytes\n%%EOF"
    print(f"OK: raw={res_a.pdf_size}B wrapper={res_b.pdf_size}B")

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "probe.py")) as f:
        src = f.read()
    raw_lines = count_loc(src, "way_a_raw_playwright")
    wrap_lines = count_loc(src, "way_b_scrapex")
    delta = raw_lines - wrap_lines
    pct = (delta / raw_lines) * 100 if raw_lines else 0.0
    print(f"RAW    Playwright : {raw_lines} non-blank/non-comment lines")
    print(f"WRAP   scrapex    : {wrap_lines} non-blank/non-comment lines")
    print(f"delta             : {delta} lines ({pct:+.1f}%)")
    if pct >= 30:
        verdict = "VALIDATED"
    elif pct >= 10:
        verdict = "PARTIAL"
    else:
        verdict = "INVALIDATED"
    print(f"VERDICT           : {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
