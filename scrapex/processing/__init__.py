"""HTML → clean markdown.

We use :mod:`trafilatura` for the heavy lifting (it handles boilerplate
removal, table preservation, and link extraction well) and post-process
to normalise whitespace.
"""
from __future__ import annotations

import re

try:
    import trafilatura

    _HAS_TRAFILATURA = True
except ImportError:  # pragma: no cover
    _HAS_TRAFILATURA = False


_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n{3,}")


def _fallback_to_bs4(html: str) -> str:
    """Best-effort fallback when trafilatura returns nothing."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def html_to_markdown(html: str, *, max_chars: int | None = None) -> str:
    """Convert HTML to clean markdown.

    Falls back to a basic BeautifulSoup strip if trafilatura isn't installed
    (it is a hard dependency, but keep the fallback for testing/dev).
    """
    if _HAS_TRAFILATURA:
        # ``favor_precision`` aggressively drops short isolated elements like
        # <h1> and standalone prices — too lossy for a scraping library.
        # Default (recall-balanced) keeps more of the page; downstream code
        # can post-filter if needed.
        md = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_images=True,
            include_tables=True,
        )
        if not md:
            # Trafilatura is conservative — for short / unusual pages it
            # returns nothing. Fall back to a simple BS4-based strip so the
            # caller still gets *something* useful.
            md = _fallback_to_bs4(html)
    else:  # pragma: no cover
        md = _fallback_to_bs4(html)
    md = _WS_RE.sub(" ", md)
    md = _NL_RE.sub("\n\n", md)
    md = md.strip()
    if max_chars is not None and len(md) > max_chars:
        md = md[:max_chars].rsplit("\n", 1)[0] + "\n\n[…truncated]"
    return md


def chunk_markdown(md: str, *, max_chars: int = 2000, overlap: int = 200) -> list[str]:
    """Split markdown into RAG-friendly chunks by paragraph boundaries."""
    if md is None:
        # Explicit guard — the previous ``if not md`` silently accepted None
        # (since ``not None`` is True) which masked caller bugs. Make it loud.
        raise TypeError("chunk_markdown() requires a str; got None")
    if not md:
        return []
    paras = [p.strip() for p in md.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 > max_chars and buf:
            chunks.append(buf)
            # carry the tail of the previous chunk for context
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = (tail + "\n\n" + p).strip() if tail else p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        chunks.append(buf)
    return chunks


__all__ = ["chunk_markdown", "html_to_markdown"]
