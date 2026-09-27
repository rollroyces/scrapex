# China LLM providers

scrapex ships with 12 China-region LLM presets out of the box, with region-aware routing for models that have separate China endpoints.

## Presets

| Preset name | Provider | Default model |
|---|---|---|
| `glm-4.7` | Zhipu | glm-4 |
| `qwen3-max` | Alibaba | qwen-max |
| `qwen3-235b` | Alibaba | qwen3-235b-a22b |
| `deepseek-v3` | DeepSeek | deepseek-chat |
| `kimi-k2` | Moonshot | moonshot-v1-128k |
| `doubao-pro` | ByteDance | doubao-pro-128k |
| `minimax-abab` | MiniMax | abab6.5s-chat |
| `yi-large` | 01.AI | yi-large |
| `baichuan-4` | Baichuan | baichuan4 |
| `spark-v3` | iFlytek | spark-v3.5 |
| `ernie-4` | Baidu | (not yet supported via litellm) |
| `hunyuan-pro` | Tencent | (not yet supported via litellm) |

## Usage

```python
import asyncio
from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

result = asyncio.run(scrape(ScrapeRequest(
    url="https://example.com/",
    schema=Schema(
        strategy=ExtractionStrategy.LLM,
        fields=[FieldSpec(name="title", selector="ignored")],
    ),
    llm_model="deepseek-v3",  # preset name
    llm_api_key="...",         # or set DEEPSEEK_API_KEY env var
)))
```

## Region routing

Some providers (Moonshot, Qwen) have separate endpoints for mainland China (`api_base` differs). Use `llm_region`:

```python
result = asyncio.run(scrape(ScrapeRequest(
    url="...",
    schema=...,
    llm_model="kimi-k2",
    llm_region="cn",  # or "intl" (default)
    llm_api_key="...",
)))
```

## Env-var discovery

scrapex automatically reads `*_API_KEY` env vars for known presets. Set:

```bash
export DEEPSEEK_API_KEY="..."
export QWEN_API_KEY="..."
export MOONSHOT_API_KEY="..."
# ... etc.
```

…and you don't need to pass `llm_api_key` explicitly.

## Direct API

If your preset isn't in the table, pass a raw `litellm` model string:

```python
result = asyncio.run(scrape(ScrapeRequest(
    url="...",
    schema=...,
    llm_model="openai/your-custom-model",
    llm_api_key="...",
)))
```

## Not yet supported

`ernie-4` (Baidu Wenxin) and `hunyuan-pro` (Tencent) are listed in the preset table but **not wired up**. Both are only available via the Qianfan / Tencent Cloud platforms, which aren't in the litellm provider list. PRs welcome once upstream integration stabilizes.

## Next

- [Auto-heal](auto-heal.md) — recovery on site redesign
- [Error hints](errors.md)