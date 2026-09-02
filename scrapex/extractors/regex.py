"""Regex extractor — for unstructured text where patterns suffice."""
from __future__ import annotations

import re
from typing import Any

from scrapex.extractors import Extractor, register


class RegexExtractor(Extractor):
    """Regex-based extraction strategy. Fast, deterministic, free.

    Best for unstructured text where the document has no useful DOM
    structure (or you don't want to depend on one). HTML tags are
    stripped before matching, so patterns can target plain text.
    """

    name = "regex"

    async def extract(self, html: str, schema: Any) -> dict[str, Any]:
        """Extract values from ``html`` for every field in ``schema``.

        For each field, the first capture group is used if present,
        otherwise the full match. Invalid regex patterns and non-matches
        both yield ``None``.
        """
        # Strip tags for plain-text matching
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        out: dict[str, Any] = {f.name: None for f in schema.fields}
        for f in schema.fields:
            if not f.selector:
                continue
            try:
                m = re.search(f.selector, text, flags=re.IGNORECASE)
            except re.error:
                continue
            if m:
                out[f.name] = m.group(1) if m.lastindex else m.group(0)
        return out


register(RegexExtractor())
