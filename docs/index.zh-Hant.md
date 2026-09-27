# scrapex

AI 友善的 Python 網頁爬蟲函式庫 — 輸入 URL + schema，輸出乾淨的 Markdown + JSON。

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

## 為什麼選擇 scrapex

單頁提取函式庫。URL + 可選的自然語言目標 → 提取的欄位 + Markdown + 元數據。為 AI/RAG pipeline 設計，您需要的是乾淨的資料，不是雜亂的 HTML。

**刻意保持精簡：**

- 只抓取一個 URL，回傳一個回應
- LLM 僅用於單次 schema 合成（`Schema.from_goal`）與除錯（`Schema.heal`、`Schema.explain`）
- 無多頁爬取、無 agent 迴圈、無點擊自動化

**精簡的依賴：** 38 個核心依賴，可選的 `[llm]`、`[browser]`、`[stealth]`、`[api]` extras。

## 語言切換

- [English](index.md)
- [繁體中文](index.zh-Hant.md) ← 您目前在這裡

## 文件狀態

繁體中文版文件目前僅翻譯首頁。其餘頁面以英文顯示。歡迎貢獻翻譯！請參考 GitHub repo 的 issue tracker。

## 安裝

```bash
pip install scrapex
```