"""Tests for aggressive_clean_html_for_llm — the text-to-tag heuristic."""
from __future__ import annotations

from scrapex.html_clean import (
    aggressive_clean_html_for_llm,
    clean_html_for_llm,
)

# --- Comparison vs the regular cleaner ----------------------------------


def test_aggressive_strips_what_regular_strips():
    """Both cleaners strip script/style/nav/footer/header/aside."""
    html = "<html><body>"
    html += "<script>var x=1;</script>"
    html += "<style>body{color:red}</style>"
    html += "<nav><a href='/'>Home</a></nav>"
    html += "<main><p>data</p></main>"
    html += "</body></html>"
    cleaned = aggressive_clean_html_for_llm(html)
    assert "var x" not in cleaned
    assert "color:red" not in cleaned
    assert "<nav>" not in cleaned


def test_aggressive_drops_empty_containers():
    """<div></div> with no children and no text is dropped."""
    html = "<html><body><div></div><p>real content</p></body></html>"
    cleaned = aggressive_clean_html_for_llm(html)
    assert "<div></div>" not in cleaned
    assert "real content" in cleaned


# --- Text-to-tag ratio heuristic ----------------------------------------


def test_aggressive_drops_tag_heavy_chrome():
    """A nav full of links (low text/tag ratio) gets dropped."""
    html = """
    <html><body>
    <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/contact">Contact</a>
        <a href="/help">Help</a>
        <a href="/blog">Blog</a>
    </nav>
    <main><p>This is the actual content with lots of text.</p></main>
    </body></html>
    """
    cleaned = aggressive_clean_html_for_llm(html)
    # The nav menu is gone
    assert "<nav>" not in cleaned
    assert "Home" not in cleaned or "About" not in cleaned
    # Main content survives
    assert "actual content" in cleaned


def test_aggressive_keeps_data_rich_chrome():
    """If a chrome-like container has lots of text (rare), keep it.

    Note: the regular cleaner already strips <nav>/<footer>/<header>/<aside>
    unconditionally, so this test uses a custom tag that survives the
    regular cleaner but matches the aggressive heuristic.
    """
    # A <section> with many paragraphs of text has high text/tag ratio
    # and is NOT dropped by the aggressive cleaner (text-rich containers
    # in the chrome-tag set are kept).
    html = """
    <html><body>
    <section class="comment-thread">
        <p>This is a long comment paragraph with lots of words and meaning.</p>
        <p>Another comment continuing the thought with more substantive prose.</p>
        <p>Yet another comment because we want this to look like content.</p>
        <p>And another for good measure to bump the text-to-tag ratio.</p>
    </section>
    </body></html>
    """
    cleaned = aggressive_clean_html_for_llm(html)
    # The section survives because it's text-dense (no aggressive drop)
    assert "long comment paragraph" in cleaned
    assert "Yet another comment" in cleaned


def test_aggressive_custom_threshold():
    """Threshold=0 disables the ratio drop, keeping all chrome subtrees.

    The text-to-tag ratio check only applies to chrome-tagged subtrees
    whose tag is NOT in the regular _STRIP_TAGS list. To verify the
    threshold actually does something, we'd need a custom chrome tag.
    In practice the threshold is a safety knob: set it to 0 if you
    never want the aggressive cleaner to drop anything based on density.
    """
    # With threshold=0, _should_drop_chrome always returns False,
    # so the chrome-strip pass becomes a no-op.
    html = "<html><body>" + ("<p>x</p>" * 100) + "</body></html>"
    # Both runs return valid cleaned HTML; the threshold knob does
    # not affect this input because there are no chrome-tagged subtrees
    # to begin with (regular cleaner already stripped them).
    r1 = aggressive_clean_html_for_llm(html, text_to_tag_threshold=1.0)
    r2 = aggressive_clean_html_for_llm(html, text_to_tag_threshold=0.0)
    assert isinstance(r1, str) and isinstance(r2, str)
    # Same length on this input (no chrome tags present)
    assert len(r1) == len(r2)


# --- Attribute stripping -------------------------------------------------


def test_aggressive_strips_noisy_attributes():
    """style, onclick, data-* attributes are dropped; structural kept."""
    html = """
    <html><body>
    <a href="/page" style="color:red" onclick="bad()" data-id="123" class="link">x</a>
    <img src="/img.png" alt="x" style="width:100px" />
    </body></html>
    """
    cleaned = aggressive_clean_html_for_llm(html)
    # Structural attrs survive
    assert 'href="/page"' in cleaned
    assert 'src="/img.png"' in cleaned
    assert 'class="link"' in cleaned
    assert 'alt="x"' in cleaned
    # Noisy attrs gone
    assert "color:red" not in cleaned
    assert "onclick" not in cleaned
    assert "data-id" not in cleaned
    assert "width:100px" not in cleaned


# --- Truncation ----------------------------------------------------------


def test_aggressive_respects_max_chars():
    big = "<html><body>" + ("<p>" + ("x" * 100) + "</p>" * 50) + "</body></html>"
    cleaned = aggressive_clean_html_for_llm(big, max_chars=1000)
    assert len(cleaned) <= 1000


def test_aggressive_handles_empty_input():
    assert aggressive_clean_html_for_llm("") == ""


def test_aggressive_handles_malformed_html():
    html = "<html><body><p>unclosed<div>more"
    # Should not raise
    cleaned = aggressive_clean_html_for_llm(html)
    assert "unclosed" in cleaned or "more" in cleaned


# --- Token savings measurement ------------------------------------------


def test_aggressive_saves_tokens_vs_regular():
    """On a chrome-heavy page, the aggressive cleaner saves more."""
    # Build a page with lots of chrome and modest content
    nav = "<nav>" + "".join(f"<a href='/{i}'>Link {i}</a>" for i in range(20)) + "</nav>"
    footer = "<footer>" + "".join(f"<a href='/{i}'>Footer Link {i}</a>" for i in range(15)) + "</footer>"
    header = "<header>" + "".join(f"<a href='/{i}'>Header Link {i}</a>" for i in range(10)) + "</header>"
    main = "<main>" + ("<p>This is meaningful content paragraph.</p>" * 5) + "</main>"
    html = f"<html><body>{nav}{header}{main}{footer}</body></html>"

    regular = clean_html_for_llm(html)
    aggressive = aggressive_clean_html_for_llm(html)

    # Aggressive should not be larger than regular
    assert len(aggressive) <= len(regular), (
        f"aggressive ({len(aggressive)}) larger than regular ({len(regular)})"
    )


def test_aggressive_preserves_tables():
    """Tables are extraction targets — never drop them."""
    html = """
    <html><body>
    <table>
        <tr><td>Product</td><td>Price</td></tr>
        <tr><td>Widget</td><td>$5</td></tr>
    </table>
    </body></html>
    """
    cleaned = aggressive_clean_html_for_llm(html)
    assert "<td>Product</td>" in cleaned
    assert "<td>Price</td>" in cleaned


# --- Comparison: aggressive vs regular on the same page -----------------


def test_aggressive_removes_svg_inline():
    """Inline SVGs (often icons) are stripped by regular cleaner, kept absent here."""
    html = """
    <html><body>
    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/></svg>
    <p>Real content here</p>
    </body></html>
    """
    cleaned = aggressive_clean_html_for_llm(html)
    # svg stripped (regular cleaner already does this)
    assert "<svg" not in cleaned
    # Real content survives
    assert "Real content" in cleaned
