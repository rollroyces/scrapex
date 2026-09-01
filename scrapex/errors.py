"""Typed errors raised by scrapex.

All exceptions inherit from :class:`ScrapexError` so callers can catch the
whole family with a single ``except`` clause.
"""
from __future__ import annotations

from typing import Any


class ScrapexError(Exception):
    """Base class for every error raised by scrapex."""


class FetchError(ScrapexError):
    """Network or transport-layer error (DNS, TLS, HTTP status, timeout)."""

    def __init__(self, url: str, message: str, *, status: int | None = None) -> None:
        super().__init__(f"[{url}] {message}")
        self.url = url
        self.status = status


class RenderError(ScrapexError):
    """Browser-rendering failure (Playwright crash, JS evaluation error)."""


class ExtractionError(ScrapexError):
    """Extraction strategy could not produce a result for the page."""

    def __init__(self, strategy: str, message: str, *, payload: Any = None) -> None:
        super().__init__(f"[{strategy}] {message}")
        self.strategy = strategy
        self.payload = payload


class SchemaError(ScrapexError):
    """User-supplied schema is invalid or unparseable."""


class ConfigurationError(ScrapexError):
    """Library is misconfigured (missing dependency, bad config)."""
