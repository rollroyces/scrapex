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


__all__ = ["_STRIP_TAGS", "clean_html_for_llm", "estimate_tokens"]
