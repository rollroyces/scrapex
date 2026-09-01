"""Extractor unit tests against known HTML fixtures."""
from __future__ import annotations

import pytest

from scrapex import ExtractionStrategy, FieldSpec, Schema
from scrapex.extractors import available, get


@pytest.fixture
def product_html() -> str:
    return """
    <html><body>
      <h1 class="name">Widget Pro</h1>
      <span class="price" data-amount="99.99">$99.99</span>
      <p class="stock">In stock</p>
      <ul class="tags">
        <li>tools</li><li>gadgets</li><li>cool</li>
      </ul>
    </body></html>
    """


@pytest.mark.parametrize("strategy_name", ["css", "xpath", "regex"])
async def test_extractors_registered(strategy_name):
    assert strategy_name in available()
    get(strategy_name)  # raises if missing


async def test_css_multi_match_returns_first(product_html):
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="first_tag", selector="ul.tags li"),
            FieldSpec(name="name", selector="h1.name"),
        ],
    )
    out = await get("css").extract(product_html, schema)
    assert out["first_tag"] == "tools"
    assert out["name"] == "Widget Pro"


async def test_xpath_uses_text_default(product_html):
    schema = Schema(
        strategy=ExtractionStrategy.XPATH,
        fields=[FieldSpec(name="price", selector="//span[@class='price']")],
    )
    out = await get("xpath").extract(product_html, schema)
    assert "99.99" in str(out["price"])


async def test_unknown_extractor_raises():
    with pytest.raises(KeyError):
        get("does-not-exist")


async def test_extractor_skips_field_without_selector():
    """Fields without selectors should be silently skipped, not crash."""
    schema = Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.name"),
            FieldSpec(name="no_selector"),  # no selector set
        ],
    )
    out = await get("css").extract("<html><body><h1 class='name'>X</h1></body></html>", schema)
    assert out["title"] == "X"
    assert out["no_selector"] is None
