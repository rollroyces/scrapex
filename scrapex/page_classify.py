"""Page fingerprint / classifier — speculative helper.

WARNING: This module was added as a SPECULATIVE feature — built
before the SRPE probe ran for real. If the probe shows browser-use
classifies page types well enough on its own, this is over-engineered.
Re-evaluate after spike 006 measures a real failure mode.

What it does:
- Takes a chunk of HTML
- Returns a coarse page-type classification:
  "disclaimer" | "list" | "detail" | "form" | "search_results" | "download" | "error" | "unknown"
- Uses a fast deterministic heuristic (no LLM call)
- Pure-Python — no network, no model load

Why this might help:
- When an LLM-driven agent loops through pages of the same site,
  knowing "this is a list page, not a detail page" helps it reason
  faster and pick the right actions
- Heuristic classifier runs in <1ms (no LLM cost)

Why this might NOT help:
- GPT-4o already classifies page types accurately from the rendered DOM
- Hard-coded heuristics are brittle (a new gov-design page breaks them)
- The classification labels are arbitrary — the LLM doesn't know our labels

Design rules:
- No LLM call — must be <1ms
- Returns one of a fixed set of labels (not arbitrary strings)
- Never raises — unknown pages get "unknown"
- The classifier is intentionally simple. If accuracy matters, use
  the LLM instead.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Page type labels. Keep the set small — anything beyond these is "unknown".
# Adding more labels is a maintenance trap; the LLM can do better.
_PAGE_TYPES = frozenset(
    {
        "disclaimer",
        "list",
        "detail",
        "form",
        "search_results",
        "download",
        "error",
        "unknown",
    }
)

# Heuristic signals. Each is a (label, score) tuple. The label with
# the highest total score wins. Ties → "unknown" (don't guess).
_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    # Disclaimer: legal text + checkbox + "I have read" / "agree"
    ("disclaimer", re.compile(
        r"(terms\s+and\s+conditions|i\s+have\s+read|i\s+agree|"
        r"checkbox.*agree|click.*agree|agree\s+to\s+the)",
        re.IGNORECASE,
    )),
    # Error page: 404 / 500 / "page not found"
    ("error", re.compile(
        r"(404|500|page\s+not\s+found|access\s+denied|forbidden|"
        r"server\s+error|maintenance|service\s+unavailable)",
        re.IGNORECASE,
    )),
    # Download page: PDF link prominent
    ("download", re.compile(
        r"href=[\"'][^\"']*\.(pdf|zip|xls[x]?|doc[x]?)[\"']",
        re.IGNORECASE,
    )),
    # Search results: query echo + result count
    ("search_results", re.compile(
        r"(\d+\s+results?|showing\s+\d+|search\s+results?|"
        r"matches?\s+found|no\s+results?)",
        re.IGNORECASE,
    )),
    # Detail page: single record, lots of label-value pairs
    ("detail", re.compile(
        r"<dt[\s>]|class=[\"'][^\"']*(detail|single|record|item-info)",
        re.IGNORECASE,
    )),
    # List page: many repeated items
    ("list", re.compile(
        r"(<ul[\s>].{50,}</ul>|<table[\s>].{200,}</table>|"
        r"class=[\"'][^\"']*(list|grid|results|items|rows))",
        re.IGNORECASE | re.DOTALL,
    )),
    # Form: prominent form with submit
    ("form", re.compile(
        r"<form[\s>].{50,}</form>|<input[^>]*type=[\"']submit|"
        r"<button[^>]*type=[\"']submit",
        re.IGNORECASE | re.DOTALL,
    )),
]


def classify_page(html: str) -> str:
    """Classify an HTML page into a coarse page-type label.

    Parameters
    ----------
    html:
        Raw HTML to classify. Need not be cleaned first — the
        classifier is intentionally tolerant of messy input.

    Returns:
    -------
    str
        One of ``"disclaimer"``, ``"list"``, ``"detail"``, ``"form"``,
        ``"search_results"``, ``"download"``, ``"error"``, or
        ``"unknown"``. The empty string returns ``"unknown"``.

    Notes:
    -----
    This is a heuristic — it's fast and free but not accurate.
    For LLM-driven workflows, prefer the LLM's own classification
    if you have access to one. This helper is for cases where you
    need a quick signal without paying for an LLM call.
    """
    if not html:
        return "unknown"

    # Cheap: regex over raw HTML before we even parse it. ~0.1ms
    # for a typical page.
    scores: dict[str, int] = {}
    for label, pattern in _SIGNALS:
        matches = len(pattern.findall(html))
        if matches > 0:
            scores[label] = scores.get(label, 0) + matches

    if not scores:
        return "unknown"

    # Find the label with the highest score
    best_label = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_label]

    # If two labels tie within 1 match, refuse to guess.
    close_call = sum(1 for s in scores.values() if s >= best_score - 1)
    if close_call > 1:
        return "unknown"

    return best_label if best_label in _PAGE_TYPES else "unknown"


def _parse_signals_for_testing(html: str) -> dict[str, int]:
    """Expose the raw scoring for tests — not part of the public API."""
    if not html:
        return {}
    scores: dict[str, int] = {}
    for label, pattern in _SIGNALS:
        matches = len(pattern.findall(html))
        if matches > 0:
            scores[label] = matches
    return scores


# --- Optional: classify via structural heuristics as well ---
#
# The regex-based classifier is fast but misses pages where the
# semantics are in the structure, not the keywords. This second
# pass parses with BeautifulSoup and looks at element counts.
# ~1ms cost on a typical page.
def _structural_score(soup: BeautifulSoup) -> dict[str, int]:
    """Score page types from element structure."""
    scores: dict[str, int] = {}
    forms = soup.find_all("form")
    if forms:
        scores["form"] = len(forms) * 2
    tables = soup.find_all("table")
    if tables:
        # Big table → likely a list; small table → likely a detail
        rows = sum(len(t.find_all("tr")) for t in tables)
        if rows > 20:
            scores["list"] = rows // 5
        elif rows > 0:
            scores["detail"] = 5
    anchors = soup.find_all("a")
    pdf_links = [
        a for a in anchors
        if (href := a.get("href")) and isinstance(href, str) and href.lower().endswith(".pdf")
    ]
    if pdf_links:
        scores["download"] = len(pdf_links) * 3
    if soup.find_all("input", attrs={"type": "checkbox"}) and soup.find_all(
        string=re.compile(r"agree|terms|conditions", re.IGNORECASE)
    ):
        scores["disclaimer"] = 10
    return scores


def classify_page_v2(html: str) -> str:
    """Stronger classifier using both regex signals and structure.

    Same return labels as :func:`classify_page` but slightly slower
    (~1ms vs ~0.1ms) and more accurate on structurally-rich pages.
    """
    if not html:
        return "unknown"

    soup = BeautifulSoup(html, "lxml")
    combined: dict[str, int] = {}
    for label, pattern in _SIGNALS:
        matches = len(pattern.findall(html))
        if matches > 0:
            combined[label] = combined.get(label, 0) + matches
    for label, score in _structural_score(soup).items():
        combined[label] = combined.get(label, 0) + score

    if not combined:
        return "unknown"

    best_label = max(combined, key=combined.get)  # type: ignore[arg-type]
    best_score = combined[best_label]
    close_call = sum(1 for s in combined.values() if s >= best_score * 0.7)
    if close_call > 1:
        return "unknown"

    return best_label if best_label in _PAGE_TYPES else "unknown"


__all__ = ["classify_page", "classify_page_v2"]
