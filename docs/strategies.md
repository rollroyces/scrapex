# Extraction strategies

scrapex supports four extraction strategies. Pick the one that matches your situation.

## CSS (`ExtractionStrategy.CSS`)

**Best for:** stable, class-based DOMs. Fastest, cheapest, no LLM call.

```python
from scrapex import Schema, FieldSpec, ExtractionStrategy

schema = Schema(
    strategy=ExtractionStrategy.CSS,
    fields=[
        FieldSpec(name="title", selector="h1.product-title"),
        FieldSpec(name="price", selector="span.price"),
    ],
)
```

Selectors are standard CSS3 selectors. `attr` defaults to `"text"`; use `"href"` for link URLs.

## XPath (`ExtractionStrategy.XPATH`)

**Best for:** XML-ish content, complex ancestor/sibling relations.

```python
schema = Schema(
    strategy=ExtractionStrategy.XPATH,
    fields=[
        FieldSpec(name="title", selector="//h1[@class='product-title']"),
        FieldSpec(name="price", selector="//span[@class='price']/text()"),
    ],
)
```

XPath expressions; `attr` defaults to `"text"`.

## Regex (`ExtractionStrategy.REGEX`)

**Best for:** simple, repetitive text patterns. Doesn't understand DOM.

```python
schema = Schema(
    strategy=ExtractionStrategy.REGEX,
    fields=[
        FieldSpec(name="price", selector=r"\$\s*(\d+\.\d{2})"),
    ],
)
```

The first regex capture group is returned.

## LLM (`ExtractionStrategy.LLM`)

**Best for:** unknown structure, prose-heavy content, fast iteration.

```python
schema = Schema(
    strategy=ExtractionStrategy.LLM,
    fields=[
        FieldSpec(name="title", selector="ignored", description="The product's display name"),
    ],
)

result = await scrape(ScrapeRequest(
    url="...",
    schema=schema,
    llm_model="gpt-4o-mini",
))
```

The LLM reads the page and fills the schema. Most flexible, slowest, most expensive.

!!! note
    The `selector` field is ignored for `ExtractionStrategy.LLM` — the LLM
    extracts directly from page content. Use `description` to hint what to extract.

## Choosing a strategy

| If you... | Use |
|---|---|
| Know the page structure | CSS |
| Need to navigate DOM relationships | XPath |
| Are parsing simple, repetitive text | Regex |
| Don't know the structure yet | LLM (`Schema.from_goal()`) |
| Need to recover from a redesign | CSS + [auto-heal](auto-heal.md) |

## Next

- [Auto-heal](auto-heal.md) — automatic recovery on site redesign
- [China LLM providers](china-llm.md) — region-aware LLM routing