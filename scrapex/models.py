"""Pydantic models — the public schema of scrapex.

Everything you pass into :func:`scrapex.scrape` and everything you get back
is one of the types defined here. Keeping these models stable is the API
contract; internal modules are not.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ExtractionStrategy(str, Enum):
    """Which extractor to run after fetching + cleaning the page.

    - ``css``: CSS selectors — fastest, no LLM cost, requires known structure
    - ``xpath``: XPath selectors — same trade-offs as CSS, more flexible
    - ``regex``: Pattern matching — for unstructured text, no LLM cost
    - ``llm``: Natural-language schema — flexible, costs tokens
    - ``none``: Skip extraction, return only markdown
    """

    CSS = "css"
    XPATH = "xpath"
    REGEX = "regex"
    LLM = "llm"
    NONE = "none"


class FieldSpec(BaseModel):
    """One field in the desired output schema.

    For ``css``/``xpath``/``regex``: ``selector`` is the selector pattern,
    ``attr`` is the HTML attribute (default ``text``).
    For ``llm``: ``description`` guides the model; ``selector`` is optional
    hint to scope which part of the page to read.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Output field name")
    description: str | None = Field(
        default=None, description="Human-readable description; required for LLM strategy"
    )
    selector: str | None = Field(
        default=None, description="CSS/XPath/regex pattern (strategy-specific)"
    )
    attr: str = Field(default="text", description="HTML attribute to extract, or 'text'")
    required: bool = Field(default=False, description="Fail if missing")


class Schema(BaseModel):
    """The shape you want back from a scrape.

    Examples:
    --------
    CSS strategy::

        Schema(
            strategy=ExtractionStrategy.CSS,
            fields=[
                FieldSpec(name="title", selector="h1.product-title"),
                FieldSpec(name="price", selector="span.price", attr="data-price"),
            ],
        )

    LLM strategy::

        Schema(
            strategy=ExtractionStrategy.LLM,
            fields=[
                FieldSpec(name="price", description="Numeric product price in USD"),
                FieldSpec(name="in_stock", description="Whether the item is in stock"),
            ],
        )
    """

    model_config = ConfigDict(extra="forbid")

    strategy: ExtractionStrategy = ExtractionStrategy.LLM
    fields: list[FieldSpec] = Field(default_factory=list)


class RenderMode(str, Enum):
    """How to fetch the page."""

    HTTP = "http"  # plain httpx, fastest, no JS
    BROWSER = "browser"  # Playwright, executes JS
    AUTO = "auto"  # try HTTP first, fall back to browser on empty/JS-only markers


class ScrapeRequest(BaseModel):
    """Everything :func:`scrapex.scrape` needs."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    schema_: Schema | None = Field(default=None, alias="schema")
    render: RenderMode = RenderMode.AUTO
    timeout_s: float = Field(default=30.0, gt=0, le=300)
    user_agent: str | None = None
    proxy: str | None = None
    # LLM strategy only — see ``litellm`` model strings, or pass a
    # :func:`scrapex.china_llm` preset name (e.g. ``"deepseek-v3"``).
    llm_model: str | None = None
    llm_api_key: str | None = None
    # Region routing for China-hosted models: ``"intl"`` (default) or ``"cn"``.
    # Only takes effect for models with separate China endpoints
    # (Moonshot, Qwen).
    llm_region: Literal["intl", "cn"] = "intl"
    # Markdown output controls
    include_markdown: bool = True
    markdown_max_chars: int | None = Field(default=None, ge=100)
    # Retry
    max_retries: int = Field(default=2, ge=0, le=10)

    @field_validator("url")
    @classmethod
    def _strip_url(cls, v: HttpUrl) -> HttpUrl:
        # Pydantic HttpUrl normalises the scheme/host; nothing extra needed here.
        return v


class ExtractionResult(BaseModel):
    """One field's extracted value (or failure)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: Any | None = None
    found: bool = False
    error: str | None = None


class ScrapeResult(BaseModel):
    """What :func:`scrapex.scrape` returns."""

    model_config = ConfigDict(extra="forbid")

    url: str
    final_url: str | None = None  # after redirects
    status: int
    title: str | None = None
    markdown: str | None = None
    html: str | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)
    extraction_warnings: list[str] = Field(default_factory=list)
    render_mode_used: Literal["http", "browser"] | None = None
    elapsed_ms: int = 0
