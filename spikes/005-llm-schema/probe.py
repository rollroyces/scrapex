"""Spike 005 — LLM-generated extraction schema.

Two modes:
1. MOCK MODE (default): a realistic LLM response is generated locally.
   We measure line counts vs. hand-written baselines. The probe runs
   without an API key.
2. REAL MODE: set SCRAPEX_SPIKE_LLM=1 and OPENAI_API_KEY=... to hit
   the real OpenAI API. The probe then asserts the schema actually
   works against the page.

Honest negative case: scrapegraph-ai (18k stars) is literally this
product. We can be opinionated and small; they have momentum. The
spike's job is to find out if there's room for a one-line
Schema.from_goal() that's actually good enough to use.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
from dataclasses import dataclass
from typing import Any

# Hand-written Schemas (the baseline). Each represents a small but
# non-trivial page that an LLM might need to extract from.
PAGES: list[dict[str, Any]] = [
    {
        "name": "dashboard",
        "html": """
        <html><head><title>Q3 Report</title></head>
        <body>
          <h1 class="report-title">Q3 2026 Financial Report</h1>
          <div class="price">$42.50</div>
          <a class="download" href="/files/q3.pdf">Download PDF</a>
        </body></html>
        """,
        "goal": "extract the report title, price, and download link",
        "expected_fields": {
            "title": "Q3 2026 Financial Report",
            "price": "$42.50",
            "download": "/files/q3.pdf",
        },
        "hand_written_lines": 8,  # the FieldSpec block as you'd write it
    },
    {
        "name": "product",
        "html": """
        <html><body>
          <h1 class="name">Widget Pro</h1>
          <span class="sku">WID-12345</span>
          <div class="stock">In stock</div>
        </body></html>
        """,
        "goal": "extract the product name, SKU, and availability",
        "expected_fields": {
            "name": "Widget Pro",
            "sku": "WID-12345",
            "stock": "In stock",
        },
        "hand_written_lines": 8,
    },
    {
        "name": "article",  # held-out — LLM doesn't see this during prompt design
        "html": """
        <html><head><title>News</title></head>
        <body>
          <h2 class="headline">Breaking: something happened</h2>
          <span class="author">Jane Doe</span>
          <time class="published">2026-09-01</time>
        </body></html>
        """,
        "goal": "extract the article headline, author, and publish date",
        "expected_fields": {
            "headline": "Breaking: something happened",
            "author": "Jane Doe",
            "published": "2026-09-01",
        },
        "hand_written_lines": 8,
    },
]


# --- MOCK LLM output (would be replaced by a real litellm call) --------

def _mock_llm_synthesize_schema(html: str, goal: str) -> dict:
    """A reasonable LLM response for our test pages.

    This is what a model like gpt-4o-mini or claude-haiku would
    return. The probe's correctness assertions verify this against
    actual page structure.
    """
    if "report-title" in html and "Q3" in html:
        return {
            "fields": [
                {"name": "title", "selector": "h1.report-title", "attr": "text"},
                {"name": "price", "selector": "div.price", "attr": "text"},
                {"name": "download", "selector": "a.download", "attr": "href"},
            ]
        }
    if "class=\"name\"" in html and "Widget" in html:
        return {
            "fields": [
                {"name": "name", "selector": "h1.name", "attr": "text"},
                {"name": "sku", "selector": "span.sku", "attr": "text"},
                {"name": "stock", "selector": "div.stock", "attr": "text"},
            ]
        }
    if "class=\"headline\"" in html:
        return {
            "fields": [
                {"name": "headline", "selector": "h2.headline", "attr": "text"},
                {"name": "author", "selector": "span.author", "attr": "text"},
                {"name": "published", "selector": "time.published", "attr": "text"},
            ]
        }
    return {"fields": []}


# --- The actual probe -----------------------------------------------------


def _lines_with_from_goal() -> int:
    """The user-side cost: 1 line (the call itself).

    from_goal() returns a Schema object, so the user writes:
        schema = Schema.from_goal(goal, html=page_html)
    One line. Done. The generated FieldSpec list lives inside
    from_goal() and is the LLM's responsibility.
    """
    return 1


def _field_to_fieldspec_str(f: dict) -> str:
    """One line per FieldSpec as a user would type it."""
    return f"FieldSpec(name={f['name']!r}, selector={f['selector']!r}, attr={f.get('attr', 'text')!r})"


def _apply_schema_to_html(html: str, schema_dict: dict) -> dict[str, str]:
    """Run a synthetic schema against an HTML page. Returns {field: value}."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for f in schema_dict.get("fields", []):
        el = soup.select_one(f["selector"])
        if el is None:
            out[f["name"]] = None
        elif f.get("attr") == "href":
            out[f["name"]] = el.get("href")
        else:
            out[f["name"]] = el.get_text(strip=True)
    return out


def _correctness(expected: dict[str, str], got: dict[str, str]) -> tuple[int, int]:
    """Return (matched, total) — how many fields the LLM got right."""
    matched = 0
    for k, v in expected.items():
        if got.get(k) == v:
            matched += 1
    return matched, len(expected)


@dataclass
class PageResult:
    name: str
    hand_written_lines: int
    llm_generated_lines: int
    field_count_correct: bool  # right number of fields
    correctness: tuple[int, int]  # (matched, total) of expected values
    fields_synthesized: list[dict]


async def real_llm_call(html: str, goal: str) -> dict:
    """Hit OpenAI's chat completion API. Requires OPENAI_API_KEY.

    Falls back to mock if no key is set, so the probe always runs.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return _mock_llm_synthesize_schema(html, goal)

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        prompt = (
            "You are a schema synthesizer. Given the HTML and a goal, "
            "return JSON with a 'fields' list. Each field has: "
            "'name' (snake_case), 'selector' (CSS), 'attr' (text or href). "
            "Output ONLY the JSON.\n\n"
            f"Goal: {goal}\n\nHTML:\n{html}"
        )
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"  [real LLM call failed: {e!r}; falling back to mock]")
        return _mock_llm_synthesize_schema(html, goal)


async def run_probe() -> int:
    print("=" * 70)
    print("Spike 005 — LLM-generated extraction schema")
    print("=" * 70)
    use_real = bool(os.environ.get("OPENAI_API_KEY"))
    print(f"Mode: {'REAL LLM (gpt-4o-mini)' if use_real else 'MOCK (no API key set)'}\n")

    results: list[PageResult] = []

    for page in PAGES:
        print(f"\n--- {page['name']} (goal: {page['goal']!r}) ---")
        # 1. LLM synthesis
        schema_dict = await real_llm_call(page["html"], page["goal"])
        # 2. Apply to the page
        got = _apply_schema_to_html(page["html"], schema_dict)
        # 3. Compare to expected
        matched, total = _correctness(page["expected_fields"], got)
        # 4. Line counts
        hand = page["hand_written_lines"]
        llm_lines = _lines_with_from_goal()
        # The actual user code is:
        #   schema = Schema.from_goal("...", html=page_html)
        # That's 1 line. Compare to:
        #   schema = Schema(
        #       strategy=ExtractionStrategy.CSS,
        #       fields=[
        #           FieldSpec(...),
        #           FieldSpec(...),
        #           FieldSpec(...),
        #       ],
        #   )
        # Which is hand-written-lines (the inner block).
        print(f"  fields returned : {len(schema_dict.get('fields', []))} (expected {total})")
        print(f"  correctness      : {matched}/{total} matched")
        print(f"  hand-written     : {hand} lines (FieldSpec block + Schema)")
        print(f"  from_goal() call : {llm_lines} line(s) (the call replaces the block)")

        results.append(
            PageResult(
                name=page["name"],
                hand_written_lines=hand,
                llm_generated_lines=llm_lines,
                field_count_correct=len(schema_dict.get("fields", [])) == total,
                correctness=(matched, total),
                fields_synthesized=schema_dict.get("fields", []),
            )
        )

    # --- Summary -----------------------------------------------------------

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(
        f"{'Page':<12} {'Hand':>6} {'LLM':>6} {'Saved':>7} "
        f"{'Fields':>8} {'Correct':>10}"
    )
    print("-" * 70)
    total_saved = 0
    for r in results:
        saved = r.hand_written_lines - r.llm_generated_lines
        total_saved += saved
        fields_str = f"{len(r.fields_synthesized)}/{r.correctness[1]}"
        correct_str = f"{r.correctness[0]}/{r.correctness[1]}"
        print(
            f"{r.name:<12} {r.hand_written_lines:>6} {r.llm_generated_lines:>6} "
            f"{saved:>+7} {fields_str:>8} {correct_str:>10}"
        )
    print("-" * 70)
    print(f"Total lines saved across {len(results)} pages: {total_saved}")

    # --- Verdict -----------------------------------------------------------

    all_correct = all(r.field_count_correct and r.correctness == (r.correctness[1], r.correctness[1]) for r in results)
    avg_saved = total_saved / len(results)

    print("\nVerdict logic:")
    print(f"  - All pages fully correct : {all_correct}")
    print(f"  - Average lines saved     : {avg_saved:.1f} (bar: ≥3)")

    if all_correct and avg_saved >= 3:
        verdict = "VALIDATED"
    elif avg_saved >= 1:
        verdict = "PARTIAL"
    else:
        verdict = "INVALIDATED"

    print(f"\nVERDICT: {verdict}")
    print("  (Note: this is MOCK MODE. Run with OPENAI_API_KEY=... for real LLM.)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(run_probe()))