# Quickstart

## The CLI: 10 seconds

```bash
pip install scrapex

# Scrape a single page
scrapex https://example.com

# Extract specific fields via a schema
scrapex https://example.com --schema '{"fields":[{"name":"title","selector":"h1"}]}'
```

Output is clean markdown + a JSON blob with extracted fields.

## The Python API

### Basic scrape

```python
import asyncio
from scrapex import scrape, ScrapeRequest

result = asyncio.run(scrape(ScrapeRequest(url="https://example.com")))
print(result.markdown)
```

### CSS extraction

```python
import asyncio
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

req = ScrapeRequest(
    url="https://example.com/product",
    schema=Schema(
        strategy=ExtractionStrategy.CSS,
        fields=[
            FieldSpec(name="title", selector="h1.product-title"),
            FieldSpec(name="price", selector="span.price", attr="data-amount"),
            FieldSpec(name="link", selector="a.buy", attr="href"),
        ],
    ),
)

result = asyncio.run(scrape(req))
print(result.extracted)
# {"title": "...", "price": "42.50", "link": "https://..."}
```

### LLM-synthesized schema (`Schema.from_goal`)

If you don't know the page structure yet, describe what you want:

```python
import asyncio
from scrapex import Schema, ScrapeRequest, scrape

async def go():
    schema = Schema.from_goal(
        goal="Extract the product title and price",
        html="<html>...sample page HTML...</html>",
        llm_model="gpt-4o-mini",
    )
    result = await scrape(ScrapeRequest(url="...", schema=schema))
    print(result.extracted)

asyncio.run(go())
```

This synthesizes a schema from a natural-language goal + a sample page, then scrapes the live URL with it.

### HTTP API

scrapex ships a FastAPI wrapper:

```bash
pip install scrapex[api]
uvicorn scrapex.wrappers.fastapi_n8n:app --reload
```

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/", "render": "auto"}'
```

See [`scrapex.wrappers.n8n-http-request-node.json`](https://github.com/rollroyces/scrapex/blob/main/scrapex/wrappers/n8n-http-request-node.json) for a drop-in n8n HTTP Request node config.

## Next

- [Strategies](strategies.md) — CSS / XPath / Regex / LLM trade-offs
- [Auto-heal](auto-heal.md) — automatic recovery when a site redesigns
- [China LLM providers](china-llm.md) — region-aware LLM routing