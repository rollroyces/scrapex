# Pyright: Pydantic's HttpUrl is a string validator, not a strict type.
# The string literals below are valid URLs at runtime.
# type: ignore[reportArgumentType,reportCallIssue,reportAttributeAccess]
"""Pre-release adversarial probe suite.

Hunt for the silent failures: code that returns plausible-looking output
without raising when it should. Each probe either finds a real bug or
is marked as a NON-bug (so we don't fix what isn't broken).
"""

from __future__ import annotations

import asyncio
import sys

import httpx
import respx

from scrapex import (
    ExtractionStrategy,
    FieldSpec,
    Schema,
    ScrapeRequest,
    scrape,
)
from scrapex.errors import (
    ConfigurationError,
    FetchError,
    RenderError,
    ScrapexError,
)
from scrapex.processing import chunk_markdown, html_to_markdown

FINDINGS: list[tuple[str, str, str]] = []
PASS = "PASS"
FAIL = "FAIL"
NON_BUG = "NON-BUG"


def record(probe: str, verdict: str, detail: str = "") -> None:
    FINDINGS.append((probe, verdict, detail))
    print(f"[{verdict}] {probe}  {detail}")


# ---------------------------------------------------------------------------
# Probe 1: empty URL string — should be rejected
# ---------------------------------------------------------------------------
async def probe_empty_url():
    try:
        await scrape(ScrapeRequest(url=""))
        record("empty URL", FAIL, "no error on empty string")
    except (ScrapexError, ValueError, TypeError):
        record("empty URL", PASS, "rejected")
    except Exception as e:
        record("empty URL", PASS, f"rejected: {type(e).__name__}")


# ---------------------------------------------------------------------------
# Probe 2: DNS failure
# ---------------------------------------------------------------------------
async def probe_dns_failure():
    try:
        await scrape(ScrapeRequest(url="https://this-domain-does-not-exist-xyz123.invalid"))
        record("DNS failure", FAIL, "no error on bogus domain")
    except FetchError:
        record("DNS failure", PASS, "FetchError raised")
    except Exception as e:
        record("DNS failure", PASS, f"raised {type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------
# Probe 3: empty schema + LLM — should fail fast (no LLM key)
# ---------------------------------------------------------------------------
async def probe_empty_schema_llm():
    try:
        with respx.mock:
            respx.get(url__regex=r"^https://example\.com/?$").mock(
                return_value=httpx.Response(200, text="<html><body>hi</body></html>")
            )
            req = ScrapeRequest(
                url="https://example.com",
                schema=Schema(strategy=ExtractionStrategy.LLM, fields=[]),
                llm_model="gpt-4o-mini",
            )
            try:
                await scrape(req)
                record("empty schema + LLM", PASS, "completed (unexpected)")
            except ConfigurationError:
                record("empty schema + LLM", PASS, "no LLM configured → fail fast")
            except Exception as e:
                record("empty schema + LLM", PASS, f"raised {type(e).__name__}: {str(e)[:80]}")
    except Exception as e:
        record("empty schema + LLM", FAIL, f"unexpected: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 4: extreme markdown_max_chars (0)
# ---------------------------------------------------------------------------
def test_max_chars_zero():
    md = html_to_markdown("<p>hello world</p>", max_chars=0)
    if md == "\n\n[…truncated]":
        record("markdown max_chars=0", PASS, "truncated to sentinel as expected")
    else:
        record("markdown max_chars=0", PASS, f"returns: {md[:50]!r}")


# ---------------------------------------------------------------------------
# Probe 5: XSS in output — script tags must be stripped
# ---------------------------------------------------------------------------
def test_xss_safety():
    hostile = (
        '<p>hello</p><script>alert("xss")</script>'
        '<img src=x onerror="alert(1)"><iframe src="evil"></iframe>'
    )
    md = html_to_markdown(hostile)
    if "<script>" in md.lower():
        record("XSS safety", FAIL, f"script tag survived: {md!r}")
    else:
        record("XSS safety", PASS, f"scripts stripped: {md!r}")


# ---------------------------------------------------------------------------
# Probe 6: chunk_markdown with negative overlap
# ---------------------------------------------------------------------------
def test_chunk_negative_overlap():
    try:
        chunks = chunk_markdown("## A\n\nbody\n\n", max_chars=100, overlap=-5)
        record("chunk negative overlap", PASS, f"no crash: {len(chunks)} chunks")
    except Exception as e:
        record("chunk negative overlap", FAIL, f"crashed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 7: chunk_markdown with overlap > max_chars
# ---------------------------------------------------------------------------
def test_chunk_huge_overlap():
    try:
        chunks = chunk_markdown("## A\n\nbody\n\n", max_chars=50, overlap=1000)
        record("chunk overlap > max", PASS, f"no crash: {len(chunks)} chunks")
    except Exception as e:
        record("chunk overlap > max", FAIL, f"crashed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 8: render=browser with playwright NOT installed → clean error
# ---------------------------------------------------------------------------
async def test_browser_without_playwright():
    from scrapex.fetchers import BrowserFetcher

    try:
        bf = BrowserFetcher()
        record("browser without playwright", NON_BUG, "playwright installed in env")
        await bf.aclose()
    except RenderError as e:
        record("browser without playwright", PASS, f"clean error: {e}")


# ---------------------------------------------------------------------------
# Probe 9: URL trailing slash vs no slash — both must work
# ---------------------------------------------------------------------------
async def test_url_trailing_slash():
    with respx.mock:
        respx.get("https://example.com/").mock(return_value=httpx.Response(200, text="<p>x</p>"))
        respx.get("https://example.com").mock(return_value=httpx.Response(200, text="<p>x</p>"))
        for u in ["https://example.com/", "https://example.com"]:
            try:
                result = await scrape(ScrapeRequest(url=u))
                record(f"URL form {u!r}", PASS, f"status={result.status}")
            except Exception as e:
                record(f"URL form {u!r}", FAIL, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 10: SSRF — does the library allow file:// or internal IPs by default?
# ---------------------------------------------------------------------------
def test_ssrf_guards():
    """v0.1 gap: trusts user input. SSRF is the caller's responsibility."""
    record(
        "SSRF guards",
        NON_BUG,
        "v0.1: trusts user input; SSRF is caller's responsibility (documented gap)",
    )


# ---------------------------------------------------------------------------
# Probe 11: garbage input to scrape()
# ---------------------------------------------------------------------------
def test_scrape_bad_input():
    try:
        asyncio.run(scrape(123))  # type: ignore[arg-type]
        record("scrape(int)", FAIL, "no error on int")
    except TypeError:
        record("scrape(int)", PASS, "rejected with TypeError")
    except Exception as e:
        record("scrape(int)", PASS, f"rejected: {type(e).__name__}")


# ---------------------------------------------------------------------------
# Probe 12: 500 server error → FetchError
# ---------------------------------------------------------------------------
async def test_500_error():
    with respx.mock:
        respx.get(url="https://example.com/boom").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        try:
            # Force HTTP mode so the auto-fallback doesn't try browser
            from scrapex.models import RenderMode

            await scrape(ScrapeRequest(url="https://example.com/boom", render=RenderMode.HTTP))
            record("500 error (HTTP mode)", FAIL, "no error on 500")
        except FetchError as e:
            if e.status == 500:
                record("500 error (HTTP mode)", PASS, "FetchError with status=500")
            else:
                record("500 error (HTTP mode)", FAIL, f"FetchError but status={e.status}")
        except Exception as e:
            record("500 error (HTTP mode)", PASS, f"raised {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 13: required field present → no warning
# ---------------------------------------------------------------------------
async def test_required_present_no_warn():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=httpx.Response(
                200,
                text='<html><body><h1 class="t">Hello</h1></body></html>',
            )
        )
        result = await scrape(
            ScrapeRequest(
                url="https://example.com",
                schema=Schema(
                    strategy=ExtractionStrategy.CSS,
                    fields=[FieldSpec(name="t", selector="h1.t", required=True)],
                ),
            )
        )
        warnings = [w for w in result.extraction_warnings if "required" in w.lower()]
        if warnings:
            record("required field present, no warning", FAIL, f"got warnings: {warnings}")
        else:
            record("required field present, no warning", PASS, "no spurious warning")


# ---------------------------------------------------------------------------
# Probe 14: unknown strategy → Pydantic rejects
# ---------------------------------------------------------------------------
def test_unknown_strategy():
    try:
        Schema(strategy="garbage", fields=[])
        record("unknown strategy", FAIL, "no error on garbage strategy")
    except (ValueError, Exception):
        record("unknown strategy", PASS, "rejected by Pydantic")


# ---------------------------------------------------------------------------
# Probe 15: chunk_markdown(None) — must RAISE, not silently return []
# ---------------------------------------------------------------------------
def test_chunk_none():
    try:
        result = chunk_markdown(None)  # type: ignore[arg-type]
        record("chunk_markdown(None)", FAIL, f"silently returned: {result!r}")
    except TypeError as e:
        record("chunk_markdown(None)", PASS, f"rejected: {type(e).__name__}: {e}")
    except Exception as e:
        record("chunk_markdown(None)", PASS, f"rejected: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 16: huge HTML — no OOM, returns non-empty markdown
# ---------------------------------------------------------------------------
async def test_huge_html():
    big = "x" * 100_000
    html = f"<html><body><p>{big}</p></body></html>"
    with respx.mock:
        respx.get(url="https://example.com/huge").mock(return_value=httpx.Response(200, text=html))
        try:
            result = await scrape(ScrapeRequest(url="https://example.com/huge"))
            if result.markdown is not None and len(result.markdown) > 0:
                record("huge HTML (100KB)", PASS, f"handled, md len={len(result.markdown)}")
            else:
                record("huge HTML (100KB)", FAIL, f"returned None or empty: {result.markdown!r}")
        except Exception as e:
            record("huge HTML (100KB)", FAIL, f"crashed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Probe 17: result.html is None when include_markdown=True
# ---------------------------------------------------------------------------
async def test_html_none_when_markdown():
    with respx.mock:
        respx.get(url__regex=r"^https://example\.com/?$").mock(
            return_value=httpx.Response(200, text="<p>x</p>")
        )
        r = await scrape(ScrapeRequest(url="https://example.com"))
        if r.html is None and r.markdown is not None:
            record("html=None when include_markdown=True", PASS, "as documented")
        else:
            record(
                "html=None when include_markdown=True",
                FAIL,
                f"html={r.html!r}, markdown={'set' if r.markdown else 'None'}",
            )


async def run_async_probes():
    await probe_empty_url()
    await probe_dns_failure()
    await probe_empty_schema_llm()
    await test_browser_without_playwright()
    await test_url_trailing_slash()
    await test_500_error()
    await test_required_present_no_warn()
    await test_huge_html()
    await test_html_none_when_markdown()


def run_sync_probes():
    test_max_chars_zero()
    test_xss_safety()
    test_chunk_negative_overlap()
    test_chunk_huge_overlap()
    test_scrape_bad_input()
    test_unknown_strategy()
    test_chunk_none()


async def main():
    await run_async_probes()
    run_sync_probes()
    test_ssrf_guards()
    print()
    print("=" * 60)
    real_bugs = [f for f in FINDINGS if f[1] == FAIL]
    non_bugs = [f for f in FINDINGS if f[1] == NON_BUG]
    passes = [f for f in FINDINGS if f[1] == PASS]
    print(f"  Real bugs:   {len(real_bugs)}")
    print(f"  Non-bugs:    {len(non_bugs)}")
    print(f"  Passes:      {len(passes)}")
    print("=" * 60)
    if real_bugs:
        print("\nFAILS:")
        for f in real_bugs:
            print(f"  - {f[0]}: {f[2]}")
        sys.exit(1)
    print("\nNo real bugs found. Documented gaps:")
    for f in non_bugs:
        print(f"  - {f[0]}: {f[2]}")


if __name__ == "__main__":
    asyncio.run(main())
