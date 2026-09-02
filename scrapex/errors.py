"""Typed errors raised by scrapex.

All exceptions inherit from :class:`ScrapexError` so callers can catch the
whole family with a single ``except`` clause. Every error carries an
optional ``hint`` (human-readable suggestion for what to try next) so the
CLI and library users get actionable feedback, not just a stack trace.
"""

from __future__ import annotations

from typing import Any


class ScrapexError(Exception):
    """Base class for every error raised by scrapex."""

    hint: str | None = None

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        # Allow per-instance override of the class-level hint
        if hint is not None:
            self.hint = hint


class FetchError(ScrapexError):
    """Network or transport-layer error (DNS, TLS, HTTP status, timeout).

    Carries ``status`` (HTTP code, or None for transport errors) and
    ``url`` so the CLI can render context like:
        ✗ [https://example.com] HTTP 503
          hint: Service unavailable. Try render=browser, or retry later.
    """

    def __init__(
        self,
        url: str,
        message: str,
        *,
        status: int | None = None,
        hint: str | None = None,
    ) -> None:
        if hint is None:
            hint = self._default_hint(status)
        super().__init__(f"[{url}] {message}", hint=hint)
        self.url = url
        self.status = status

    @staticmethod
    def _default_hint(status: int | None) -> str | None:
        """Pick a sensible default hint based on the HTTP status code."""
        if status is None:
            return (
                "Transport-level failure (DNS, TLS, or timeout). "
                "Try increasing timeout_s, or check your network."
            )
        if status == 404:
            return "Page not found. If the site is JS-rendered, try render=browser."
        if status == 403:
            return "Forbidden. The site may be blocking automated requests."
        if status == 429:
            return "Rate limited. Increase delay between requests or rotate proxies."
        if 500 <= status < 600:
            return (
                f"Server error (HTTP {status}). Try render=browser, or retry with max_retries > 2."
            )
        return None


class RenderError(ScrapexError):
    """Browser-rendering failure (Playwright crash, JS evaluation error)."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        if hint is None:
            hint = (
                "Browser rendering failed. Make sure playwright is installed: "
                "pip install 'scrapex[browser]' && playwright install chromium"
            )
        super().__init__(message, hint=hint)


class ExtractionError(ScrapexError):
    """Extraction strategy could not produce a result for the page."""

    def __init__(
        self,
        strategy: str,
        message: str,
        *,
        hint: str | None = None,
        payload: Any = None,
    ) -> None:
        if hint is None:
            hint = (
                f"Strategy '{strategy}' failed. "
                "Try a different strategy (css/xpath/regex/llm) "
                "or check your schema for invalid selectors."
            )
        super().__init__(f"[{strategy}] {message}", hint=hint)
        self.strategy = strategy
        self.payload = payload


class SchemaError(ScrapexError):
    """User-supplied schema is invalid or unparseable."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        if hint is None:
            hint = "Schema is invalid. Check that fields have names, and selectors are non-empty."
        super().__init__(message, hint=hint)


class ConfigurationError(ScrapexError):
    """Library is misconfigured (missing dependency, bad config, no API key)."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        if hint is None:
            hint = (
                "Library is misconfigured. "
                "Check the README for required environment variables "
                "or extra dependencies."
            )
        super().__init__(message, hint=hint)
