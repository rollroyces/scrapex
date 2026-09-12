"""Wrappers — integration layers for orchestration tools.

The wrappers here are **opt-in**: they require their own extras
(`scrapex[api]`, etc.) and are not part of the core surface.

If you're reading the README and wondering "where's the FastAPI
wrapper? where's the n8n snippet?" — they're here, gated behind
optional installs. The core library stays small.
"""
from __future__ import annotations

__all__: list[str] = []
