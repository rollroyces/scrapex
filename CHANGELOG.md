# Changelog

All notable changes to scrapex are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `python -m scrapex synth <goal>` subcommand — synthesize a Schema
  from a natural-language goal + HTML. Supports `--synth-url <url>` to
  fetch live HTML, or `--html-file <path>` for offline mode. Outputs
  the schema as JSON to stdout (or to `--synth-output <file>`).
  Auto-detects Ollama or OpenAI when `--synth-model` isn't given. One
  LLM call per invocation (~$0.0002-$0.0008 on gpt-4o-mini).

## [0.2.1] - 2026-09-13

### Removed

- `scrapex.selector_rank` — speculative feature built without measurement.
  The git history has it (commits before v0.2.1) if anyone needs to
  revive it with benchmarks.
- `scrapex.page_classify` — speculative feature built without measurement.
  The regex-based v1 had a known bug (returned "unknown" on disclaimer
  pages); the BS4-based v2 wasn't benchmarked. Removed per the lesson
  in `docs/speculative.md`: "build → measure → graduate" is the right
  workflow, not "build → label speculative → ship."

## [0.2.0] - 2026-09-13

### Added

- `Schema.heal(html, llm_model=None)` — single-shot LLM call that patches
  CSS/XPath/Regex selectors when a site redesigns its DOM. Returns a new
  `Schema`; original is untouched.
- `ScrapeRequest.auto_heal: bool = True` — orchestrator-level opt-in. When
  extraction returns empty for every field on a browser-rendered page,
  `scrape()` calls `Schema.heal()` once and re-extracts.
- `Schema.from_goal(goal, html, llm_model=None)` — synthesizes a schema
  from a natural-language goal + a sample page's HTML.
- `Schema.explain()` — explains what a schema extracts, for documentation
  or debugging.
- `scrapex.contrib.sessions.Session` — opt-in cookie jar with sensitive-name
  guards. Survives across calls.
- `scrapex.contrib.captcha.solve_captcha_human_in_loop(page)` — opt-in
  human-in-the-loop CAPTCHA pause/resume using a local browser.
- `scrapex.fetchers.CloudscraperFetcher` — opt-in Cloudflare bypass via
  `cloudscraper`. Wire it through `ScrapeRequest(stealth=True)`.
- `scrapex.wrappers.fastapi_n8n` — FastAPI wrapper exposing POST `/scrape`
  and GET `/health`. Optional `[api]` extra.
- `scrapex.wrappers.n8n-http-request-node.json` — drop-in n8n HTTP Request
  node config.
- `scrapex.html_clean.aggressive_clean_html_for_llm()` — three-pass DOM
  pruner (chrome subtree drop, empty container collapse, attribute noise
  stripping). Reduces LLM input tokens ~71%.
- `scrapex.china_llm` — 12 China-region LLM presets (DeepSeek, Qwen, GLM,
  Moonshot, etc.) with region-aware routing.
- CLI with Rich output and status-aware error hints.
- GitHub Actions CI: `ruff check`, `mypy`, `pytest` (coverage-gated at
  80%), running on every push to `main` and every PR.
- Branch protection: `main` requires the `lint + types + tests` job
  before any PR merges. Force-push and branch deletion are blocked.
- Integration test harness (`tests/integration/`): real-LLM tests for
  `Schema.heal()` (skipped without API key) and HTTP-fixture tests using
  recorded real-world HTML (Wikipedia, httpbin, example.com).

### Changed

- HTML cleaner now strips `<nav>`, `<header>`, `<footer>`, `<aside>`,
  `<style>`, `<script>`, `<noscript>`, `<iframe>`, `<svg>`, and comments
  before LLM calls. Total LLM token reduction: 71% per call.
- LLM prompts (`_PROMPT_TEMPLATE`, `_PROMPT` in healer,
  `_EXTRACTION_PROMPT`) tightened: explicit "ONLY JSON / No prose /
  No markdown fences" framing at the top, concrete examples where they
  reduce malformed-JSON failure modes.
- `Schema.from_goal()` defaults to `lenient=True` (returns even on partial
  LLM failures; warnings surface in `extraction_warnings`).
- `FieldSpec.attr` validation: only `"text"` or `"href"` accepted.
- README rewritten with new sections: contrib modules, China LLM
  providers, auto-heal, CI/branch protection.

### Fixed

- `[stealth]` extra was declared but `cloudscraper` was never imported.
  Now wired through `CloudscraperFetcher` and activated by
  `ScrapeRequest(stealth=True)`.
- `chunk_markdown(None)` silently returned `[]`; now raises `TypeError`
  on `None` input.
- `_parse_schema` in CLI ignored `--strategy llm`; now honors the flag
  and defaults `llm_model="gpt-4o-mini"` when `--strategy llm` is used
  without `--preset`.

### Removed

_(none)_

### Honest caveats

- Real-LLM quality for `Schema.from_goal` and `Schema.heal` is **not**
  measured in this sandbox. The integration test harness in
  `tests/integration/test_heal_live.py` is the only honest way to verify;
  it requires `OPENAI_API_KEY`.
- The auto-heal trigger is narrowed to browser-rendered pages only.
  HTTP-only fetches (where empty extraction usually means "needs JS to
  render") don't fire heal.
- Speculative helpers `selector_rank` and `page_classify` are in the
  codebase but **not in the public API**. They were built without
  measurement and may be removed in v0.3.0 if benchmarks show no value.

## [0.1.0] - 2026-09-01

Initial release. Single-page extraction: URL + optional natural-language
goal → extracted fields + markdown + metadata. AGPL-3.0-or-later +
commercial dual license. 38 hard dependencies, opt-in `[llm]`, `[browser]`,
`[stealth]`, `[api]`, `[dev]` extras.
