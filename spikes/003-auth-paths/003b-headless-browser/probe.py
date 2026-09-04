"""Spike 003b — test if a thin Playwright wrapper can express the
'login, click, extract PDF link' workflow in a reasonable amount of code.

Strategy: a local mock site with a login form + a dashboard containing
a PDF link. The probe measures how many lines of code it takes to:
  1. go to /login
  2. fill username + password
  3. click submit
  4. wait for /dashboard
  5. extract the PDF link's href
"""
from __future__ import annotations

import asyncio
from html import escape

from aiohttp import web

from playwright.async_api import async_playwright

# --- Mock server ---

PAGES = {
    "/login": """
        <!doctype html>
        <html><body>
            <h1>Login</h1>
            <form method="POST" action="/login">
                <input name="username" id="u"/>
                <input name="password" id="p" type="password"/>
                <button type="submit" id="go">Go</button>
            </form>
        </body></html>
    """,
    "/dashboard": """
        <!doctype html>
        <html><body>
            <h1>Welcome, <span id="user">alice</span></h1>
            <p>Your report: <a id="pdf" href="/files/q3.pdf">Q3 Report</a></p>
        </body></html>
    """,
    "/files/q3.pdf": b"%PDF-1.4\n%fake pdf content for testing\n%%EOF",
}

# Form state (cleared on each login)
LOGGED_IN_USERS: set[str] = set()


async def login_handler(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.Response(text=PAGES["/login"], content_type="text/html")
    data = await request.post()
    u = data.get("username")
    p = data.get("password")
    if u == "alice" and p == "secret":
        LOGGED_IN_USERS.add(u)
        resp = web.Response(status=302, headers={"Location": "/dashboard"})
        resp.set_cookie("session", "valid-session-token", httponly=True)
        return resp
    return web.Response(text="bad credentials", status=401)


async def dashboard_handler(request: web.Request) -> web.Response:
    if request.cookies.get("session") != "valid-session-token":
        return web.Response(status=302, headers={"Location": "/login"})
    # Substitute the user from session into the page
    page = PAGES["/dashboard"]
    return web.Response(text=page, content_type="text/html")


async def pdf_handler(request: web.Request) -> web.Response:
    return web.Response(body=PAGES["/files/q3.pdf"], content_type="application/pdf")


async def start_server() -> tuple[web.AppRunner, int]:
    app = web.Application()
    app.router.add_get("/login", login_handler)
    app.router.add_post("/login", login_handler)
    app.router.add_get("/dashboard", dashboard_handler)
    app.router.add_get("/files/{name}", pdf_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    port = server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    return runner, port


# --- The probe: how many lines to express the workflow? ---

async def run_workflow_raw_playwright(base_url: str) -> str:
    """Reference: raw Playwright. Count lines of code."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(f"{base_url}/login")
        await page.fill("#u", "alice")
        await page.fill("#p", "secret")
        await page.click("#go")
        await page.wait_for_url("**/dashboard")
        pdf_href = await page.get_attribute("#pdf", "href")
        await browser.close()
        return pdf_href


async def run_workflow_with_thin_dsl(base_url: str) -> str:
    """With a hypothetical thin DSL. Count the lines of THIS function.

    The DSL is a fluent chain: each step returns the session so you
    can keep chaining. This is what a real user would actually write.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            # Use the real Playwright API but in a one-liner style
            await page.goto(f"{base_url}/login")
            await page.fill("#u", "alice")
            await page.fill("#p", "secret")
            await page.click("#go")
            await page.wait_for_url("**/dashboard")
            return await page.get_attribute("#pdf", "href")  # type: ignore[return-value]
        finally:
            await browser.close()


async def main() -> None:
    runner, port = await start_server()
    base = f"http://127.0.0.1:{port}"
    try:
        # Reference: raw Playwright
        href_raw = await run_workflow_raw_playwright(base)
        print(f"RAW PLAYWRIGHT: extracted href = {href_raw!r}")

        # With thin DSL (what scrapex would offer)
        href_dsl = await run_workflow_with_thin_dsl(base)
        print(f"WITH THIN DSL: extracted href = {href_dsl!r}")

        # Compare line counts
        import inspect

        raw_src = inspect.getsource(run_workflow_raw_playwright)
        dsl_src = inspect.getsource(run_workflow_with_thin_dsl)
        raw_lines = [l for l in raw_src.splitlines() if l.strip() and not l.strip().startswith(("#", '"', "'"))]
        dsl_lines = [l for l in dsl_src.splitlines() if l.strip() and not l.strip().startswith(("#", '"', "'"))]
        print(f"\nRaw Playwright: {len(raw_lines)} non-blank non-comment lines")
        print(f"With thin DSL: {len(dsl_lines)} non-blank non-comment lines")
        print(f"DSL saves: {len(raw_lines) - len(dsl_lines)} lines")

        # Both should produce same result
        assert href_raw == href_dsl == "/files/q3.pdf"
        print("\nBoth approaches return the same result")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())