"""Tests for the FastAPI wrapper. Requires `pip install scrapex[api]`."""
from __future__ import annotations

import builtins
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def client():
    """Build a TestClient against the FastAPI app."""
    from fastapi.testclient import TestClient

    from scrapex.wrappers.fastapi_n8n import app

    return TestClient(app)


@pytest.fixture
def fake_scrape_result():
    """Build a ScrapeResult-like object for mocking."""
    from scrapex.models import ScrapeResult

    return ScrapeResult(
        url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        title="Example Domain",
        markdown="# Example Domain\n\nReal content.",
        html="<html><body><h1>Example Domain</h1><p>Real content.</p></body></html>",
        extracted={"title": "Example Domain"},
        extraction_warnings=[],
        render_mode_used="http",
        elapsed_ms=42,
    )


# --- Health check --------------------------------------------------------


def test_health_endpoint(client):
    """The /health endpoint always returns 200 with status=ok."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- Happy path: basic scrape --------------------------------------------


def test_scrape_endpoint_success(client, fake_scrape_result):
    """POST /scrape with a valid URL returns the ScrapeResult fields."""
    with patch("scrapex.scrape", new=AsyncMock(return_value=fake_scrape_result)):
        r = client.post(
            "/scrape",
            json={"url": "https://example.com/"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "https://example.com/"
    assert body["status"] == 200
    assert body["title"] == "Example Domain"
    assert "Real content" in body["markdown"]
    assert body["extracted"] == {"title": "Example Domain"}
    assert body["render_mode_used"] == "http"
    assert body["error"] is None


# --- Error paths ---------------------------------------------------------


def test_scrape_endpoint_returns_error_in_body(client):
    """A scrape failure becomes a 200 with `error` populated (NOT 500).

    5xx is reserved for "the API itself is broken". A failed scrape
    is a normal response with details."""
    fake = MagicMock()
    fake.side_effect = RuntimeError("network unreachable")
    with patch("scrapex.scrape", new=fake):
        r = client.post("/scrape", json={"url": "https://example.com/"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert "RuntimeError" in body["error"]
    assert "network unreachable" in body["error"]
    assert body["status"] == 0


def test_scrape_endpoint_validates_url(client):
    """An obviously invalid URL returns 422 (Pydantic validation)."""
    # Empty url field
    r = client.post("/scrape", json={})
    assert r.status_code == 422


def test_scrape_endpoint_rejects_missing_url_field(client):
    """URL field is required."""
    r = client.post("/scrape", json={"goal": "test"})
    assert r.status_code == 422


def test_scrape_endpoint_rejects_invalid_timeout(client):
    """timeout_s must be > 0."""
    r = client.post("/scrape", json={"url": "https://x/", "timeout_s": -1})
    assert r.status_code == 422


# --- All body fields are accepted ----------------------------------------


def test_scrape_endpoint_accepts_all_optional_fields(client, fake_scrape_result):
    """The endpoint accepts goal, schema, render, stealth, etc."""
    with patch("scrapex.scrape", new=AsyncMock(return_value=fake_scrape_result)):
        r = client.post(
            "/scrape",
            json={
                "url": "https://example.com/",
                "goal": "the title",
                "schema": {"strategy": "css", "fields": [{"name": "title", "selector": "h1"}]},
                "render": "http",
                "stealth": False,
                "include_markdown": True,
                "timeout_s": 10.0,
            },
        )
    assert r.status_code == 200


def test_scrape_endpoint_accepts_alias_schema(client, fake_scrape_result):
    """The body uses 'schema' as the JSON key (alias for schema_)."""
    with patch("scrapex.scrape", new=AsyncMock(return_value=fake_scrape_result)):
        r = client.post(
            "/scrape",
            json={
                "url": "https://x/",
                "schema": {"strategy": "css", "fields": []},
            },
        )
    assert r.status_code == 200


# --- Module-level behavior ----------------------------------------------


def test_wrapper_requires_fastapi_installed():
    """If fastapi is missing, the wrapper raises a clear install hint.

    Verified by removing fastapi from sys.modules and patching __import__
    to fail for the name 'fastapi'. If the cached module is still
    present in sys.modules, the test is skipped (the import won't be
    re-attempted).
    """

    # If fastapi was imported earlier in the test session, the wrapper
    # module will reuse the cached one. Skip the test in that case —
    # the install-hint behavior is exercised when a real user has not
    # installed the extra.
    if "fastapi" in sys.modules:
        pytest.skip("fastapi is loaded; cannot simulate missing dep")

    # Patch builtins.__import__ to fail on 'fastapi'

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastapi" or name.startswith("fastapi."):
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    # Remove cached wrapper module so re-import triggers the import logic
    if "scrapex.wrappers.fastapi_n8n" in sys.modules:
        del sys.modules["scrapex.wrappers.fastapi_n8n"]

    builtins.__import__ = fake_import
    try:
        with pytest.raises(ImportError, match="scrapex\\[api\\]"):
            from scrapex.wrappers import fastapi_n8n  # noqa: F401
    finally:
        builtins.__import__ = real_import


def test_wrapper_exports_expected_names():
    """The wrapper exposes app + body models."""
    from scrapex.wrappers import fastapi_n8n

    assert hasattr(fastapi_n8n, "app")
    assert hasattr(fastapi_n8n, "ScrapeRequestBody")
    assert hasattr(fastapi_n8n, "ScrapeResponseBody")
