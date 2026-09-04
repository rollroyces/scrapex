"""CSS-selector extractor — deterministic, no LLM, fast."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from scrapex.extractors import Extractor, register


class CssExtractor(Extractor):
    """CSS selector-based extraction strategy. Fast, deterministic, free.

    Best for pages with stable structure where you know the selectors
    ahead of time. Each :class:`~scrapex.FieldSpec` uses its ``selector`` as
    a CSS selector and ``attr`` to pick text / HTML / an HTML attribute.
    """

    name = "css"

    async def extract(self, html: str, schema: Any) -> dict[str, Any]:
        """Extract values from ``html`` for every field in ``schema``.

        Every field name in ``schema`` appears in the returned dict, with
        ``None`` for fields that couldn't be extracted. Missing or invalid
        selectors yield ``None`` rather than raising.
        """
        soup = BeautifulSoup(html, "lxml")
        # Pre-populate every field so callers can rely on the key existing,
        # even if extraction failed or the field has no selector.
        out: dict[str, Any] = {f.name: None for f in schema.fields}
        for f in schema.fields:
            if not f.selector:
                continue
            try:
                el = soup.select_one(f.selector)
            except Exception:
                continue  # out[f.name] already None
            if el is None:
                continue
            if f.attr == "text":
                out[f.name] = el.get_text(strip=True)
            elif f.attr == "html":
                out[f.name] = str(el)
            else:
                val = el.get(f.attr)
                if val is not None:
                    out[f.name] = val
        return out


register(CssExtractor())
