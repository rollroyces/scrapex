# scrapex

AI 友好的 Python 网页爬虫库 — 输入 URL + schema，输出干净的 Markdown + JSON。

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
        ],
    ),
)

result = asyncio.run(scrape(req))
print(result.markdown)
print(result.extracted)
```

## 为什么选择 scrapex

单页提取库。URL + 可选的自然语言目标 → 提取的字段 + Markdown + 元数据。为 AI/RAG 管道设计，您需要的是干净的数据，不是杂乱的 HTML。

**刻意保持精简：**

- 只抓取一个 URL，返回一个响应
- LLM 仅用于单次 schema 合成（`Schema.from_goal`）与调试（`Schema.heal`、`Schema.explain`）
- 无多页爬取、无 agent 循环、无点击自动化

**精简的依赖：** 38 个核心依赖，可选的 `[llm]`、`[browser]`、`[stealth]`、`[api]` extras。

## 语言切换

- [English](index.md)
- [简体中文](index.zh-Hans.md) ← 您当前在这里

## 文档状态

简体中文版文档目前仅翻译首页。其余页面以英文显示。欢迎贡献翻译！请参考 GitHub repo 的 issue tracker。

## 安装

```bash
pip install scrapex
```