"""XPath extractor — same trade-offs as CSS, more flexible for nested cases."""

from __future__ import annotations

from typing import Any

from lxml import html as lxml_html

from scrapex.extractors import Extractor, register


class XpathExtractor(Extractor):
    """XPath-based extraction strategy. Fast, deterministic, free.

    Best when CSS selectors get awkward — nested traversal, conditional
    selection based on element position or attributes. Uses lxml under
    the hood, which supports XPath 1.0.
    """

    name = "xpath"

    async def extract(self, html: str, schema: Any) -> dict[str, Any]:
        """Extract values from ``html`` for every field in ``schema``.

        For each field, the first matching node is used. Fields with no
        match or invalid XPath return ``None``. Every field name appears
        in the result dict, even if the value is ``None``.
        """
        tree = lxml_html.fromstring(html)
        out: dict[str, Any] = {f.name: None for f in schema.fields}
        for f in schema.fields:
            if not f.selector:
                continue
            try:
                nodes = tree.xpath(f.selector)
            except Exception:
                continue
            if not nodes:
                continue
            node = nodes[0]
            if f.attr == "text":
                out[f.name] = (node.text or "").strip() if hasattr(node, "text") else str(node)
            elif f.attr == "html":
                out[f.name] = lxml_html.tostring(node, encoding="unicode")
            else:
                out[f.name] = node.get(f.attr) if hasattr(node, "get") else None
        return out


register(XpathExtractor())
