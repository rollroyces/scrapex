# Integration tests for `Schema.heal()`

These tests verify `Schema.heal()` against real-world conditions.
They're separate from the main unit tests because some require
network or API keys.

## Files

| File | What it does | When to run |
|---|---|---|
| `test_heal_live.py` | Real LLM calls (OpenAI / DeepSeek / Ollama) | When you have an API key |
| `test_heal_real_websites.py` | Real HTTP via in-process server + recorded HTML fixtures | Every commit (works without API keys) |
| `fixtures/*.html` | Real HTML recorded from real sites | Recorded once, frozen |
| `conftest.py` | Shared fixtures (fixture_server) | — |

## Running

```bash
# Without API key (just the real-HTTP tests)
pytest tests/integration/ -v

# With API key (runs everything)
OPENAI_API_KEY=*** pytest tests/integration/ -v

# Force-skip live tests
SKIP_LIVE=1 pytest tests/integration/ -v

# Just the live tests (requires key)
OPENAI_API_KEY=*** pytest tests/integration/test_heal_live.py -v

# Compare models (needs multiple keys or local Ollama)
OPENAI_API_KEY=sk-... DEEPSEEK_API_KEY=... pytest tests/integration/test_heal_live.py -v -k comparison
```

## What's recorded in fixtures/

The `fixtures/` directory contains HTML captured from real sites:

- `example-com.html` — `https://example.com/` (559 bytes, simple page)
- `httpbin-html.html` — `https://httpbin.org/html` (3.7 KB, Herman Melville quote)
- `wikipedia-python.html` — `https://en.wikipedia.org/wiki/Python_(programming_language)` (1 MB, stress test)

These were captured once. To re-capture (e.g. if a fixture becomes
stale), use curl or the helper in `conftest.py`:

```python
from tests.integration.conftest import FIXTURES_DIR
import urllib.request
url = "https://example.com/"
req = urllib.request.Request(url, headers={"User-Agent": "scrapex-fixture-recorder/1.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    (FIXTURES_DIR / "example-com.html").write_bytes(r.read())
```

## Why an HTTP fixture server instead of recording JSON?

Real websites return real HTML with real network behavior (status
codes, content-types, redirects). A JSON fixture would miss edge
cases in:

- BeautifulSoup parsing of slightly malformed HTML
- The HTML cleaner (whitespace, comments, scripts)
- The fetcher's error handling on real HTTP responses

A local HTTP server with recorded body gives us 100% of real
behavior with 0% flakiness.

## Why this isn't a "live test against real sites"?

Real sites change. A test that hits `example.com` and asserts
"page has `<h1>` with 'Example Domain'" would break tomorrow if
the site redesigns. The fixtures are frozen at a known version,
so tests pass deterministically across runs.

For LLM-quality measurement (does the LLM produce good selectors
on real-world pages?), use `test_heal_live.py` — that hits the
LLM directly with synthetic scenarios, which is more reproducible
than relying on whichever site you happen to point at.
