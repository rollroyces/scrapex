"""Extractor protocol + registry.

Each strategy is a module under ``scrapex.extractors.*`` that exposes an
async ``extract(html, schema) -> dict`` function. The protocol here is the
contract.
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scrapex.models import Schema


class Extractor(abc.ABC):
    """Abstract base — implementations live in sibling modules."""

    name: str = "abstract"

    @abc.abstractmethod
    async def extract(
        self, html: str, schema: Schema
    ) -> dict[str, Any]:
        """Return ``{field_name: value, ...}``.

        Missing fields may be omitted; the caller will record warnings.
        """


# Registry — populated by the strategy modules on import.
# IMPORTANT: strategies are imported at the BOTTOM of this file (after the
# protocol is defined) to avoid circular imports.
_REGISTRY: dict[str, Extractor] = {}


def register(extractor: Extractor) -> None:
    """Add an extractor instance to the global registry."""
    _REGISTRY[extractor.name] = extractor


def get(name: str) -> Extractor:
    """Look up an extractor by name; raises :class:`KeyError` if missing."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown extractor '{name}'. Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def available() -> list[str]:
    return sorted(_REGISTRY)


# Now import the strategy modules so they register themselves.
# Side-effecting imports at the bottom is the standard fix for circular deps.
from scrapex.extractors import css as _css  # noqa: E402, F401
from scrapex.extractors import llm as _llm  # noqa: E402, F401
from scrapex.extractors import regex as _regex  # noqa: E402, F401
from scrapex.extractors import xpath as _xpath  # noqa: E402, F401

__all__ = ["Extractor", "available", "get", "register"]
