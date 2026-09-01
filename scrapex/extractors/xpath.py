"""XPath extractor — same trade-offs as CSS, more flexible for nested cases."""
from __future__ import annotations

from typing import Any

from lxml import html as lxml_html

from scrapex.extractors import Extractor, register


class XpathExtractor(Extractor):
    name = "xpath"

    async def extract(self, html: str, schema: Any) -> dict[str, Any]:
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
