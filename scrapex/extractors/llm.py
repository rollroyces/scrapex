"""LLM extractor — natural-language schema via :mod:`litellm`.

Lazy-imports ``litellm`` so users who never set ``strategy=llm`` don't pay
the import cost. Falls back to a clear error if ``litellm`` isn't installed.
"""

from __future__ import annotations

import json
from typing import Any

from scrapex.errors import ConfigurationError, ExtractionError
from scrapex.extractors import Extractor, register

_EXTRACTION_PROMPT = """\
You are a precise data extractor. Read the page content below and return a
JSON object matching the requested schema. Output ONLY the JSON — no prose,
no markdown fences.

Schema (JSON):
{schema}

Page content:
{content}
"""


class LlmExtractor(Extractor):
    """LLM-based extraction strategy. Flexible, costs tokens.

    Best for pages where you don't know the structure ahead of time —
    just describe what you want in natural language. Uses :mod:`litellm`
    under the hood, so every provider litellm supports is supported here.

    Costs: each call consumes tokens. For high-volume scraping, prefer
    CSS/XPath/Regex when the structure is stable.
    """

    name = "llm"

    def __init__(self) -> None:
        # Keep an Optional[Any] so Pyright doesn't unify with ``None``
        self._litellm: Any = None

    def _ensure_litellm(self) -> None:
        """Lazy-import :mod:`litellm` on first extract. Cached after.

        Raises :class:`~scrapex.ConfigurationError` if litellm isn't
        installed (caller didn't include the ``llm`` extra).
        """
        if self._litellm is not None:
            return
        try:
            import litellm

            self._litellm = litellm
        except ImportError as e:
            raise ConfigurationError(
                "LLM strategy requires the 'llm' extra: pip install 'scrapex[llm]'"
            ) from e

    async def extract(
        self,
        html: str,
        schema: Any,
        *,
        llm_model: str | None = None,
        llm_api_key: str | None = None,
        markdown: str | None = None,
        api_base: str | None = None,
    ) -> dict[str, Any]:
        """Extract values from ``html`` for every field in ``schema``.

        Sends the (markdown-preferred, truncated) page content and the
        schema to the LLM, asks for JSON-only output, and returns the
        model's answer mapped to field names. Returns only the schema's
        fields — anything else the model invented is dropped.

        Parameters
        ----------
        llm_model:
            The litellm model string (e.g. ``"gpt-4o-mini"``,
            ``"deepseek/deepseek-chat"``).
        llm_api_key, api_base:
            Optional overrides; if not set, litellm falls through to its
            own env-var discovery.
        markdown:
            Pre-cleaned markdown of the page. When provided, used in
            preference to raw ``html``.

        Raises:
        ------
        ConfigurationError:
            If ``llm_model`` is missing or litellm isn't installed.
        ExtractionError:
            If the LLM call fails or returns non-JSON.
        """
        self._ensure_litellm()
        if not llm_model:
            raise ConfigurationError("LLM strategy requires llm_model to be set")
        # Reduce payload size — send markdown (cleaner) over raw HTML when available
        content = markdown if markdown else html
        if len(content) > 100_000:
            content = content[:100_000] + "\n\n[...truncated]"
        schema_json = json.dumps(
            {
                "fields": [
                    {"name": f.name, "description": f.description or f.name}
                    for f in schema.fields
                ]
            },
            indent=2,
        )
        prompt = _EXTRACTION_PROMPT.format(schema=schema_json, content=content)
        # Only pass api_key / api_base if explicitly set — letting them fall
        # through as None lets litellm pick up provider env vars itself.
        call_kwargs: dict[str, Any] = {
            "model": llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        if llm_api_key:
            call_kwargs["api_key"] = llm_api_key
        if api_base:
            call_kwargs["api_base"] = api_base
        try:
            resp = await self._litellm.acompletion(**call_kwargs)
        except Exception as e:
            raise ExtractionError("llm", f"LLM call failed: {e}") from e
        text = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ExtractionError("llm", f"LLM returned non-JSON: {text[:200]}") from e
        # Coerce to schema field names — drop anything the model invented
        out: dict[str, Any] = {}
        for f in schema.fields:
            out[f.name] = data.get(f.name)
        return out


_llm_instance = LlmExtractor()
register(_llm_instance)


def get_llm_extractor() -> LlmExtractor:
    """Return the process-wide singleton LlmExtractor instance."""
    return _llm_instance
