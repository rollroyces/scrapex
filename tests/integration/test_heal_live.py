"""Live integration test for Schema.heal().

Run with a real LLM API key. Skipped by default (no API key in CI).

Usage:
    OPENAI_API_KEY=*** python -m pytest tests/integration/test_heal_live.py -v
    OPENAI_API_KEY=*** python -m pytest tests/integration/test_heal_live.py -v -k ollama
    DEEPSEEK_API_KEY=*** python -m pytest tests/integration/test_heal_live.py -v -k deepseek

These tests do REAL network calls. Each test costs ~$0.001 in tokens.
Skip them with `-m "not integration"` or set SKIP_LIVE=1.
"""
from __future__ import annotations

import os

import pytest


def _ollama_reachable() -> bool:
    """True if Ollama is running on the default port. Cheap HTTP probe."""
    try:
        import httpx

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        r = httpx.get(f"{host}/api/tags", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


# Skip this whole file if no API key is set OR if SKIP_LIVE=1
SKIP_LIVE = os.environ.get("SKIP_LIVE", "0") == "1"
HAS_OPENAI = bool(os.environ.get("OPENAI_API_KEY"))
HAS_OLLAMA = bool(os.environ.get("OLLAMA_HOST")) or _ollama_reachable()
HAS_DEEPSEEK = bool(os.environ.get("DEEPSEEK_API_KEY"))

HAS_ANY_LLM = HAS_OPENAI or HAS_OLLAMA or HAS_DEEPSEEK

# Skip only the live-LLM tests (not the smoke report).
live_skipif = pytest.mark.skipif(
    SKIP_LIVE or not HAS_ANY_LLM,
    reason=(
        "Live LLM tests require OPENAI_API_KEY, DEEPSEEK_API_KEY, "
        "or a running Ollama instance. Set SKIP_LIVE=1 to force-skip."
    ),
)


# --- Test fixtures -------------------------------------------------------


def _build_broken_schema_and_target_html():
    """A realistic broken-schema scenario.

    The broken schema targets class names that DON'T exist in the
    current HTML (simulating a site redesign). The new HTML uses
    different class names. The heal should patch at least the
    obvious ones.
    """
    from scrapex import FieldSpec, Schema
    from scrapex.models import ExtractionStrategy

    broken = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.OLD-title-class-2024"),
            FieldSpec(name="body", selector="div.OLD-body-text-2024"),
            FieldSpec(name="date", selector="time.OLD-date-class"),
        ],
    )
    # The new HTML — uses different class names but the data is there
    new_html = """
    <html>
    <body>
        <article>
            <h1 class="article-title-2026">The Q3 2026 Report</h1>
            <div class="article-body">
                <p>Revenue was $5.2B in Q3 2026, up 12% YoY.</p>
            </div>
            <time class="published-at" datetime="2026-09-01">2026-09-01</time>
        </article>
    </body>
    </html>
    """
    return broken, new_html


def _build_obvious_renamed_schema():
    """Easier scenario: the schema just had its class names changed."""
    from scrapex import FieldSpec, Schema
    from scrapex.models import ExtractionStrategy

    broken = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.product-title"),  # old class
        ],
    )
    new_html = """
    <html><body>
        <h1 class="product-title-v2">Widget Pro</h1>
    </body></html>
    """
    return broken, new_html


def _build_unchanged_schema():
    """Sanity check: when the schema is already correct, heal keeps it."""
    from scrapex import FieldSpec, Schema
    from scrapex.models import ExtractionStrategy

    broken = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1"),
        ],
    )
    new_html = "<html><body><h1>Hello</h1></body></html>"
    return broken, new_html


# --- Helper -------------------------------------------------------------


def _pick_model() -> str:
    """Pick the cheapest available model based on env vars."""
    if HAS_OPENAI:
        return "gpt-4o-mini"
    if HAS_DEEPSEEK:
        return "deepseek/deepseek-chat"
    if HAS_OLLAMA:
        return "ollama/qwen2.5:1.5b"
    raise RuntimeError("No LLM available — check env vars")


# --- Tests --------------------------------------------------------------


@pytest.mark.asyncio
@live_skipif
async def test_heal_patches_obviously_renamed_class():
    """The trivial case: class renamed. The LLM should find the new one.

    This is the lowest bar — if the LLM can't find a class that's
    named `product-title-v2` when asked to find `product-title`, the
    feature is broken.
    """
    from scrapex.html_clean import clean_html_for_llm
    from scrapex.schema_healer import _heal_schema

    broken, new_html = _build_obvious_renamed_schema()
    cleaned = clean_html_for_llm(new_html)

    healed = _heal_schema(broken, cleaned, llm_model=_pick_model())
    by_name = {f.name: f for f in healed.fields}
    # Either the LLM patched it, or it kept the original selector.
    # We don't assert correctness — we just print what we got.
    print("\n  Original: h1.product-title")
    print(f"  Healed:   {by_name['title'].selector}")
    print(f"  Reason:   {by_name['title'].description}")
    assert by_name["title"].selector  # non-empty


@pytest.mark.asyncio
@live_skipif
async def test_heal_realistic_redesign():
    """The realistic case: 3 fields, all renamed. Document what works."""
    from scrapex.html_clean import clean_html_for_llm
    from scrapex.schema_healer import _heal_schema

    broken, new_html = _build_broken_schema_and_target_html()
    cleaned = clean_html_for_llm(new_html)

    healed = _heal_schema(broken, cleaned, llm_model=_pick_model())
    print("\n  Field-by-field heal results:")
    print(f"  {'name':<8} {'original':<35} {'healed':<35}")
    print(f"  {'-'*8} {'-'*35} {'-'*35}")
    for orig, new in zip(broken.fields, healed.fields, strict=True):
        patched = "←PATCHED" if orig.selector != new.selector else "(kept)"
        print(f"  {orig.name:<8} {orig.selector:<35} {new.selector:<35} {patched}")

    # We don't assert all 3 fields were patched — the LLM may skip
    # ones it's not confident about (by design). We just verify
    # the function returned without raising.
    assert len(healed.fields) == 3


@pytest.mark.asyncio
@live_skipif
async def test_heal_keeps_already_correct_schema():
    """Sanity check: when the schema already works, heal doesn't break it."""
    from scrapex.html_clean import clean_html_for_llm
    from scrapex.schema_healer import _heal_schema

    broken, new_html = _build_unchanged_schema()
    cleaned = clean_html_for_llm(new_html)

    healed = _heal_schema(broken, cleaned, llm_model=_pick_model())
    by_name = {f.name: f for f in healed.fields}
    # The selector MIGHT change (LLM might rewrite it). Or stay.
    # Either way, the new selector should still match the title.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(new_html, "lxml")
    el = soup.select_one(by_name["title"].selector)
    assert el is not None, (
        f"Heal broke a working selector: {by_name['title'].selector!r} no longer matches"
    )
    assert el.get_text(strip=True) == "Hello"


# --- Comparison helper --------------------------------------------------


@pytest.mark.asyncio
@live_skipif
async def test_heal_model_comparison():
    """Run the same heal with different models and report accuracy.

    This is informational, not a strict pass/fail test. It tells
    you which model to use for healing in production.
    """
    if not HAS_OLLAMA:
        pytest.skip("Ollama comparison requires a local Ollama instance")

    from scrapex.html_clean import clean_html_for_llm
    from scrapex.schema_healer import _heal_schema

    broken, new_html = _build_broken_schema_and_target_html()
    cleaned = clean_html_for_llm(new_html)

    models = []
    if HAS_OPENAI:
        models.append("gpt-4o-mini")
    if HAS_DEEPSEEK:
        models.append("deepseek/deepseek-chat")
    if HAS_OLLAMA:
        models.append("ollama/qwen2.5:1.5b")

    print("\n  Heal results by model:")
    print(f"  {'model':<30} {'title':<10} {'body':<10} {'date':<10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")
    for model in models:
        try:
            healed = _heal_schema(broken, cleaned, llm_model=model)
            by_name = {f.name: f for f in healed.fields}
            row = (
                "PATCHED" if by_name["title"].selector != broken.fields[0].selector else "kept",
                "PATCHED" if by_name["body"].selector != broken.fields[1].selector else "kept",
                "PATCHED" if by_name["date"].selector != broken.fields[2].selector else "kept",
            )
            print(f"  {model:<30} {row[0]:<10} {row[1]:<10} {row[2]:<10}")
        except Exception as e:
            print(f"  {model:<30} FAILED: {type(e).__name__}: {e}")


# --- Reporting ----------------------------------------------------------


def test_smoke_report():
    """Print a smoke report of what's available. Always runs (informational)."""
    print("\n  Live LLM test environment:")
    print(f"    SKIP_LIVE:           {SKIP_LIVE}")
    print(f"    OPENAI_API_KEY:      {'set' if HAS_OPENAI else 'not set'}")
    print(f"    DEEPSEEK_API_KEY:    {'set' if HAS_DEEPSEEK else 'not set'}")
    print(f"    OLLAMA (reachable):  {HAS_OLLAMA}")
    if SKIP_LIVE or not (HAS_OPENAI or HAS_OLLAMA or HAS_DEEPSEEK):
        print("    No LLM available — heal tests will be skipped.")
        print("    Run with: OPENAI_API_KEY=*** pytest tests/integration/test_heal_live.py")
    else:
        print(f"    Selected model:      {_pick_model()}")
    # This test always passes — it's informational
    assert True
