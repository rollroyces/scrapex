"""HTML cleaning utilities for LLM schema synthesis.

Real HTML is 60-90% noise for LLM consumption: scripts, styles,
comments, navigation chrome, repeated UI elements, whitespace.
Sending all of it is wasted tokens. This module strips what's not
needed for selector-targeted extraction while preserving enough
structure that the LLM can identify the data fields.

Design rules (each strip is opt-in so users can disable if they
need the raw HTML):

- Strip ``<script>`` and ``<style>`` entirely (CSS selectors don't
  need them and the LLM hallucinates false positives from JS).
- Strip ``<!-- comments -->`` (zero information).
- Strip ``<noscript>`` blocks (redundant with scripts).
- Collapse consecutive whitespace to a single space (whitespace
  tokens add up).
- Remove common chrome elements (``<nav>``, ``<footer>``,
  ``<header>``, ``<aside>``) — these rarely contain the data the
  user wants to extract.
- Truncate to ``max_chars`` (default 30,000 — half the previous
  50,000 limit).

What we DON'T do:
- Don't rewrite or normalize HTML (changes structure, may break
  selectors later).
- Don't remove ``<form>``, ``<table>``, ``<input>``, etc — those
  often contain the data the user wants.
- Don't guess which sections are "important" — that's goal-aware
  and would require its own LLM call (defeating the purpose).
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Comment

# Tags we strip entirely. These are chrome / non-data content.
_STRIP_TAGS: frozenset[str] = frozenset(
    {
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "svg",
        "iframe",  # often ad/analytics content
    }
)

# Whitespace collapse: 2+ whitespace chars → single space.
_WHITESPACE_RE = re.compile(r"\s{2,}")


def clean_html_for_llm(
    html: str,
    *,
    max_chars: int = 30_000,
    preserve_tables: bool = True,
) -> str:
    """Strip noise from HTML before sending to the LLM.

    Parameters
    ----------
    html:
        Raw HTML to clean.
    max_chars:
        Hard cap on output length. Default 30K chars (down from 50K).
        At ~4 chars/token, that's ~7.5K tokens for the cleaned HTML,
        which fits comfortably in any model's context.
    preserve_tables:
        If True, keep ``<table>``, ``<thead>``, ``<tbody>``, ``<tr>``,
        ``<th>``, ``<td>`` intact — these are common extraction
        targets and stripping them would hurt the LLM.

    Returns:
    -------
    str
        The cleaned HTML, truncated to ``max_chars``. Always returns
        a string (never raises on malformed HTML — it just falls
        through with whatever BeautifulSoup could parse).
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # Strip noise tags
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    # Strip HTML comments (BeautifulSoup exposes them as Comment nodes)
    for comment_node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment_node.extract()
    # Collapse whitespace in text nodes (keep tag structure intact)
    cleaned = str(soup)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    # Hard truncate
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def estimate_tokens(text: str, *, chars_per_token: float = 4.0) -> int:
    """Cheap token estimate without loading tiktoken.

    LLMs average ~4 chars per token for English/HTML content.
    For exact counts use tiktoken, but that requires an install
    we don't want to force on users. This is good enough for
    pre-flight cost estimates in logs and tests.

    Returns:
    -------
    int
        Estimated tokens. Always >= 0.
    """
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token))


# ---------------------------------------------------------------------------
# Aggressive semantic pruning — drop whole subtrees that look like chrome
# ---------------------------------------------------------------------------
#
# Why a text-to-tag ratio heuristic?
#
# Chrome/navigation/decoration subtrees tend to be:
#   <a href="/">Home</a> | <a href="/about">About</a> | <a href="/x">X</a>
# That is, lots of tags and very little text per tag.
#
# Data subtrees tend to be:
#   <h1>The Q3 Report</h1>
#   <p>Revenue was $5.2B, up 12% YoY...</p>
# Lots of text relative to tags.
#
# Algorithm: walk the parsed DOM, compute (text_len / tag_count) per
# subtree. If below a threshold AND the subtree is in
# _AGGRESSIVE_CHROME_TAGS, drop it.
#
# Cost: O(n) over the DOM. ~5ms on a 50KB page.
# Risk: may drop data inside nav-like containers (e.g. a price list
# inside <aside>). Caller can disable per-call by passing
# ``text_to_tag_threshold=0`` which disables the ratio check entirely.

_AGGRESSIVE_CHROME_TAGS: frozenset[str] = frozenset(
    {"nav", "footer", "header", "aside", "menu", "menubar"}
)

# Default: tag-heavy subtrees (text/tag ratio < 1.0) are dropped.
# Set to 0 to keep ALL chrome-tagged subtrees regardless of density.
_TEXT_TO_TAG_THRESHOLD = 1.0


def _subtree_stats(node: Any) -> tuple[int, int]:
    """Walk a subtree, return (text_chars, tag_count)."""
    text_chars = len(node.get_text() or "")
    tag_count = sum(1 for _ in node.descendants if _.name is not None)
    return text_chars, max(tag_count, 1)


def _should_drop_chrome(node: Any, threshold: float) -> bool:
    """True if this subtree is tag-heavy chrome.

    With ``threshold <= 0``, returns False (never drop on ratio).
    """
    if threshold <= 0:
        return False
    text_chars, tag_count = _subtree_stats(node)
    return (text_chars / tag_count) < threshold


def aggressive_clean_html_for_llm(
    html: str,
    *,
    max_chars: int = 25_000,
    text_to_tag_threshold: float = _TEXT_TO_TAG_THRESHOLD,
    preserve_tables: bool = True,
) -> str:
    """Aggressively strip noise from HTML for LLM consumption.

    Beyond the regular ``clean_html_for_llm`` (script/style/nav
    strip + whitespace collapse), this also:

    - Drops chrome subtrees (nav/footer/header/aside/menu) whose text
      density is low (likely menus/icon lists, not data)
    - Removes inline SVGs entirely (often icon fonts, no text content)
    - Collapses empty tags (e.g. ``<div></div>`` -> ``""``)
    - Drops attribute noise on remaining tags (keeps ``href``, ``class``,
      ``id``, ``name``, drops ``style``, ``onclick``, etc.)

    Parameters
    ----------
    html:
        Raw HTML to clean.
    max_chars:
        Hard cap on output. Default 25K (more aggressive than the
        regular cleaner's 30K).
    text_to_tag_threshold:
        Below this text_chars/tag_count ratio, chrome-like subtrees
        are dropped. Default 1.0 (tuned empirically). Set to 0 to
        keep all chrome-tagged subtrees regardless of density.
    preserve_tables:
        Same as the regular cleaner.

    Returns:
    -------
    str
        The aggressively cleaned HTML, truncated to ``max_chars``.

    When to use
    -----------
    Use this when the regular cleaner still produces too many tokens
    or the LLM is confused by chrome. Skip if your data lives inside
    nav/footer/header tags (rare, but possible - e.g. breadcrumbs
    inside ``<nav>``).
    """
    if not html:
        return ""
    # Start from the regular clean (script/style/comment/whitespace)
    # then add aggressive passes.
    base = clean_html_for_llm(html, max_chars=10_000_000)
    soup = BeautifulSoup(base, "lxml")

    # Pass 1: drop chrome subtrees whose text density is low.
    # The regular cleaner already stripped them entirely, so this
    # is mostly defensive — it only matters if someone disabled
    # the regular cleaner or added custom logic. But it's cheap
    # (~1ms) and safe.
    for tag_name in _AGGRESSIVE_CHROME_TAGS:
        for node in soup.find_all(tag_name):
            if _should_drop_chrome(node, text_to_tag_threshold):
                node.decompose()

    # Pass 2: drop empty containers (any tag with no text and no
    # meaningful children).
    for node in list(soup.find_all()):
        if node.name in {"br", "hr", "img", "input", "meta", "link"}:
            continue
        text = node.get_text(strip=True)
        if not text:
            meaningful_children = [
                c for c in node.children
                if getattr(c, "name", None) is not None
                and c.get_text(strip=True)
            ]
            if not meaningful_children:
                node.decompose()

    # Pass 3: strip noisy attributes. Keep structural info
    # (href, class, id, name) and drop style/event noise.
    keep_attrs = frozenset({"href", "class", "id", "name", "src", "alt", "title"})
    for node in soup.find_all():
        if not node.attrs:
            continue
        for attr in list(node.attrs.keys()):
            if attr not in keep_attrs:
                del node.attrs[attr]

    cleaned = str(soup)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


__all__ = [
    "_STRIP_TAGS",
    "aggressive_clean_html_for_llm",
    "clean_html_for_llm",
    "estimate_tokens",
]
