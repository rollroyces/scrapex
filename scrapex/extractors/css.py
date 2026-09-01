"""CSS-selector extractor — deterministic, no LLM, fast."""
from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from scrapex.extractors import Extractor, register


class CssExtractor(Extractor):
    name = "css"

    async def extract(self, html: str, schema: Any) -> dict[str, Any]:
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
