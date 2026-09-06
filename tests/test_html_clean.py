"""Tests for the HTML cleaner and prompt token optimization."""
from __future__ import annotations

import tiktoken

from scrapex.html_clean import clean_html_for_llm, estimate_tokens
from scrapex.schema_synth import _PROMPT_TEMPLATE

# --- Token count assertions (the proof that we improved) ----------------


def test_prompt_template_token_count():
    """The prompt overhead must stay under 130 tokens.

    If you add anything to the prompt, this test fails. That's the
    point — keep prompts lean.
    """
    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    n = len(enc.encode(_PROMPT_TEMPLATE))
    assert n < 130, f"prompt is {n} tokens, expected <130"
    assert n > 50, f"prompt is only {n} tokens, expected >50 (probably broken)"


def test_prompt_template_shrunk_vs_baseline():
    """Compared to the original verbose prompt (206 tokens), we should
    be saving >40%."""
    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    new_tokens = len(enc.encode(_PROMPT_TEMPLATE))
    baseline = 206
    savings_pct = (baseline - new_tokens) / baseline * 100
    assert savings_pct >= 40, f"savings only {savings_pct:.0f}%, target >=40%"


# --- HTML cleaner behavior ----------------------------------------------


def test_clean_html_strips_scripts():
    html = "<html><body><script>var x = 1;</script><h1>Hello</h1></body></html>"
    cleaned = clean_html_for_llm(html)
    assert "script" not in cleaned.lower() or "var x" not in cleaned
    assert "Hello" in cleaned


def test_clean_html_strips_styles():
    html = "<html><head><style>body { color: red; }</style></head><body><p>hi</p></body></html>"
    cleaned = clean_html_for_llm(html)
    assert "color: red" not in cleaned
    assert "<p>hi</p>" in cleaned


def test_clean_html_strips_comments():
    html = "<html><body><!-- TODO --><p>visible</p></body></html>"
    cleaned = clean_html_for_llm(html)
    assert "TODO" not in cleaned
    assert "visible" in cleaned


def test_clean_html_strips_nav():
    html = (
        "<html><body>"
        "<nav><a href='/'>Home</a></nav>"
        "<article><h1>Real content</h1></article>"
        "</body></html>"
    )
    cleaned = clean_html_for_llm(html)
    assert "Home" not in cleaned
    assert "Real content" in cleaned


def test_clean_html_strips_footer_header_aside():
    html = (
        "<html><body>"
        "<header>Logo</header>"
        "<main><p>data</p></main>"
        "<aside>related</aside>"
        "<footer>copyright</footer>"
        "</body></html>"
    )
    cleaned = clean_html_for_llm(html)
    assert "Logo" not in cleaned
    assert "copyright" not in cleaned
    assert "related" not in cleaned
    assert "data" in cleaned


def test_clean_html_collapses_whitespace():
    html = "<p>hello    world\n\n\nfoo</p>"
    cleaned = clean_html_for_llm(html)
    # No triple newlines, no runs of whitespace > 1
    assert "\n\n\n" not in cleaned
    assert "    " not in cleaned  # 4 spaces
    # The content is preserved
    assert "hello" in cleaned
    assert "world" in cleaned
    assert "foo" in cleaned


def test_clean_html_preserves_tables():
    """Tables are common extraction targets — never strip them."""
    html = (
        "<html><body>"
        "<table><tr><td>Price</td><td>$5</td></tr></table>"
        "</body></html>"
    )
    cleaned = clean_html_for_llm(html)
    assert "<td>Price</td>" in cleaned
    assert "<td>$5</td>" in cleaned


def test_clean_html_preserves_forms_and_inputs():
    """Forms and inputs often contain the data to extract."""
    html = (
        "<html><body>"
        "<form><input name='email' value='x@y.com' /></form>"
        "</body></html>"
    )
    cleaned = clean_html_for_llm(html)
    assert "email" in cleaned
    assert "x@y.com" in cleaned


def test_clean_html_handles_empty_input():
    assert clean_html_for_llm("") == ""
    assert clean_html_for_llm(None) == ""  # type: ignore[arg-type]


def test_clean_html_truncates_at_max_chars():
    big = "<p>" + ("x" * 100_000) + "</p>"
    cleaned = clean_html_for_llm(big, max_chars=5000)
    assert len(cleaned) <= 5000


def test_clean_html_reduces_size():
    """Real-world HTML should be meaningfully smaller after cleaning."""
    html = """
    <html>
    <head>
        <script src="jquery.js"></script>
        <style>body { background: white; }</style>
        <!-- analytics -->
        <script>analytics.track('pageview');</script>
    </head>
    <body>
        <nav><a href="/">Home</a><a href="/about">About</a></nav>
        <header><h1>Site Header</h1></header>
        <main>
            <article>
                <h2>The Q3 Report</h2>
                <p>Revenue was $5.2B, up 12% YoY.</p>
                <a href="/q3.pdf" class="download">Download PDF</a>
            </article>
        </main>
        <aside><p>Related articles</p></aside>
        <footer><p>Copyright 2026</p></footer>
    </body>
    </html>
    """
    cleaned = clean_html_for_llm(html)
    assert len(cleaned) < len(html) / 2, (
        f"cleaning only saved {1 - len(cleaned)/len(html):.0%} — check the strip list"
    )
    # Important content survives
    assert "Q3 Report" in cleaned
    assert "$5.2B" in cleaned
    assert "/q3.pdf" in cleaned


def test_clean_html_does_not_break_on_malformed():
    """Garbage in, sensible out."""
    html = "<html><body><p>unclosed<p>another<p>third"
    cleaned = clean_html_for_llm(html)
    assert "unclosed" in cleaned or "another" in cleaned


# --- estimate_tokens helper --------------------------------------------


def test_estimate_tokens_handles_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_handles_typical_text():
    # 4 chars per token, so 100 chars = 25 tokens (rounded)
    n = estimate_tokens("x" * 100)
    assert 20 <= n <= 30


def test_estimate_tokens_is_cheap():
    """No tiktoken import — pure arithmetic. Verify it's instant."""
    import time

    t0 = time.perf_counter()
    for _ in range(10_000):
        estimate_tokens("<html>" + "x" * 1000)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"10K calls took {elapsed:.2f}s, expected <0.5s"


# --- End-to-end: prompt size with realistic HTML ------------------------


def test_end_to_end_prompt_under_token_target():
    """The full prompt (template + goal + cleaned HTML) should be under
    10K tokens for a typical 200KB page. That's the optimization
    target — anything above this means we should clean more."""
    # Realistic-ish noisy page
    html = (
        "<html><head>"
        + ("<script>analytics.track();</script>" * 50)
        + "</head><body>"
        + "<nav>nav</nav>"
        + ("<article><h2>News</h2><p>...</p></article>" * 50)
        + "<footer>footer</footer>"
        + "</body></html>"
    )
    cleaned = clean_html_for_llm(html)
    full_prompt = _PROMPT_TEMPLATE.format(goal="the news titles", html=cleaned)
    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    n = len(enc.encode(full_prompt))
    # 50 articles x ~30 chars/article + prompt overhead
    assert n < 1500, f"prompt is {n} tokens for a clean page, target <1500"
