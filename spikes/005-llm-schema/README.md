# Spike 005 — LLM-generated extraction schema

## Verdict: PARTIAL (in mock mode)

**Honest result, with the caveat spelled out clearly:**

| Metric | Result | Bar | Pass? |
|---|---|---|---|
| Lines saved per call (mock) | **7** | ≥3 | ✓ |
| Mock correctness | 3/3 pages | 100% | ✓ |
| Real LLM correctness | **NOT TESTED** | 100% | — |
| Real LLM latency | **NOT TESTED** | <5s | — |

The mock proves the **shape** of the feature: `Schema.from_goal(goal, html)` is 1 line vs 8 for hand-typed. The mock does NOT prove the LLM actually produces correct schemas on real pages.

## What the mock probe did

Three pages: a dashboard (3 fields), a product (3 fields), a news article (3 fields, held out — not in the prompt design). For each:

- Hand-written: 8 lines (Schema + strategy + fields list + 3 FieldSpecs)
- `from_goal()` call: 1 line
- **Saved 7 lines per call**

The mock LLM produced 3 fields with the right CSS selectors for all three pages. Mock output matched expected values 3/3.

## What this DOESN'T prove

The mock is a hand-written dict that returns the right answer for our specific test pages. The real questions are:

1. **Does a real LLM (gpt-4o-mini or claude-haiku) produce correct selectors
   on real-world pages?** It might hallucinate fields, miss obvious ones, or
   pick fragile selectors.
2. **Is the LLM response time acceptable?** Even cheap models have a
   200-500ms round-trip. For high-volume scraping, that's a real cost.
3. **Are the generated selectors maintainable?** When the site changes
   next month, the user can't fix a selector they didn't write.

To test these, run with `OPENAI_API_KEY=...` set:

```bash
OPENAI_API_KEY=sk-... python spikes/005-llm-schema/probe.py
```

The probe will hit the real API and apply the same correctness checks. We
didn't run this because no API key is available in this environment.

## What would change my mind

- **5 consecutive real LLM calls all return correct schemas** on pages
  the LLM hasn't seen prompt examples for. If 5/5 pass, the feature is
  real. If even 1/5 fails on a real-world page, ship only with a
  documented "review the generated schema" warning.
- **The LLM response is fast enough** (<3s for gpt-4o-mini). If it's
  slow, this feature is dead on arrival for high-volume use.
- **The user can still understand what the LLM generated.** A method
  like `schema.explain()` that says "I picked `h1.report-title` because
  it looked like the title in your HTML" would mitigate the "user
  can't fix what they didn't write" problem.

## What I recommend

**Build the feature, but be conservative about defaults.**

1. `Schema.from_goal(goal, html)` is real and useful. 7 lines saved per
   call, 100% correctness on the mock. The shape is right.

2. **The feature is opt-in.** The user calls `from_goal()` explicitly;
   `Schema(strategy=..., fields=...)` is still the default. No surprise
   LLM calls on the hot path.

3. **Add `schema.explain()`** — returns a list of human-readable reasons
   for each field's selector. This addresses the "user can't fix what
   they didn't write" concern.

4. **The README must document:** "from_goal() calls an LLM. Set
   OPENAI_API_KEY (or use a China preset). Verify the generated schema
   before relying on it for production."

5. **Don't try to compete with scrapegraph-ai's full LLM-pipeline story.**
   scrapex's value-add is the schema synthesis, not the orchestration.
   scrapegraph already does the full thing — we offer the small piece.

## Risks if we ship

| Risk | Mitigation |
|---|---|
| LLM hallucinates a field | `correctness` field in result, warn in docs |
| LLM picks fragile selectors | Document; user can edit the returned schema |
| LLM call costs money | Doc clearly; user opts in |
| LLM response time | Cache by `(html_hash, goal)` for repeated pages |
| LLM API down | `from_goal()` raises; user can fall back to hand-typed |

## Implementation plan if we ship

```
scrapex/
├── schema_synth.py        Schema.from_goal() implementation (~80 LOC)
└── (test file)             test_schema_synth.py

README.md                  +Schema synthesis section with example
```

Cost: ~80 LOC of source + ~150 LOC of tests. We mock the LLM in
tests with the same approach this spike used.

## Honest final take

The mock result is a positive signal but not a green light. The spike
proves that the **shape** of the feature is right. The real LLM test
is the next step. If the user is willing to run the real probe with
their API key and report back, I can build the feature with confidence.
If not, the safe move is to skip it — `Schema(strategy=..., fields=...)`
is 8 lines and works today.