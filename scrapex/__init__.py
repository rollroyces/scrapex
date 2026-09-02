"""scrapex — AI-friendly web scraping for Python.

Public API surface (the only things intended to be imported by users):

    from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

The rest of the package is implementation detail.
"""

from __future__ import annotations

from scrapex import china_llm as china
from scrapex.errors import (
    ConfigurationError,
    ExtractionError,
    FetchError,
    RenderError,
    SchemaError,
    ScrapexError,
)
from scrapex.models import (
    ExtractionResult,
    ExtractionStrategy,
    FieldSpec,
    RenderMode,
    Schema,
    ScrapeRequest,
    ScrapeResult,
)
from scrapex.scrape import scrape

__version__ = "0.1.0"

__all__ = [
    "ConfigurationError",
    "ExtractionError",
    "ExtractionResult",
    "ExtractionStrategy",
    "FetchError",
    "FieldSpec",
    "RenderError",
    "RenderMode",
    "Schema",
    "SchemaError",
    "ScrapeRequest",
    "ScrapeResult",
    "ScrapexError",
    "__version__",
    "china",
    "scrape",
]
