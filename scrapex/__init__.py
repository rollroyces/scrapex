"""scrapex — AI-friendly web scraping for Python.

Public API surface (the only things intended to be imported by users):

    from scrapex import scrape, ScrapeRequest, Schema, FieldSpec, ExtractionStrategy

The rest of the package is implementation detail.
"""

from __future__ import annotations

import contextlib

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


def _attach_schema_synthesis() -> None:
    """Lazy-monkey-patch Schema.from_goal() and Schema.explain().

    These methods live in :mod:`scrapex.schema_synth` which depends on
    :mod:`litellm` (a non-default dep). We don't import the module at
    package load — that would force every scrapex user to install the
    [llm] extra. Instead, we attach the methods lazily:

    - On first import of scrapex, the methods are *not* yet attached.
    - On first call to ``Schema.from_goal()`` or ``Schema.explain()``,
      we import the module and attach the methods.

    The attachment is idempotent. Once attached, the methods stay.
    """
    if hasattr(Schema, "from_goal") and hasattr(Schema, "explain"):
        return
    # Import is intentional — it attaches the methods on Schema as a
    # side effect (see schema_synth module-level code).
    from scrapex import schema_synth  # noqa: F401


# Make the methods available at package load. This is the "eager
# attach" path: if litellm is installed, the methods work. If not,
# the lazy path above catches it on first call and raises a clear
# ConfigurationError instead of AttributeError.
with contextlib.suppress(Exception):
    _attach_schema_synthesis()


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
