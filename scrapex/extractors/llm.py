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
    name = "llm"

    def __init__(self) -> None:
        # Keep an Optional[Any] so Pyright doesn't unify with ``None``
        self._litellm: Any = None

    def _ensure_litellm(self) -> None:
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
    return _llm_instance
