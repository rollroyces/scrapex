"""Schema auto-healing for broken CSS selectors.

When a website redesigns its DOM, existing ``Schema`` objects with
hard-coded CSS selectors stop working. ``Schema.heal()`` accepts a
broken schema + the new HTML, asks an LLM to identify which
selectors are likely broken, and returns a patched schema with
working selectors.

Contract (strictly enforced):

- ONE LLM call. No retries, no loops, no agent reasoning.
- Stateless. The caller decides when to call it.
- Opt-in. ``Schema.heal()`` is a method that touches the LLM;
  the rest of scrapex works without it.
- Returns a ``Schema``. The caller owns the new schema; the
  original is untouched.

Design rules:

- The LLM gets the broken schema's fields, the new HTML (already
  cleaned by ``html_clean.clean_html_for_llm``), and a tight prompt
  that asks for a JSON dict of ``{field_name: new_selector}``.
- Fields the LLM can't confidently fix are kept as-is (original
  selector) and returned with a warning.
- Malformed LLM responses raise :class:`ConfigurationError` — we
  don't silently return the broken schema.

When to use:

- You have a saved ``Schema`` from yesterday
- Today the page returns empty results
- You want a one-shot LLM patch without rewriting the schema manually

When NOT to use:

- The page is JS-rendered (use ``render=RenderMode.BROWSER`` instead)
- You don't have an LLM API key (use hand-written selectors)
- You want a guaranteed fix (LLMs can guess wrong; always verify)
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scrapex.errors import ConfigurationError
from scrapex.html_clean import clean_html_for_llm

if TYPE_CHECKING:
    pass


# Tight prompt — minimal prose, schema-first.
# The LLM returns {"fixes": [{"name": str, "selector": str, "reason": str}, ...]}.
# Only fields where the LLM is confident get a fix; missing fields
# mean "keep the original selector."
_PROMPT = """\
You are a CSS selector fixer. Given an HTML page and a list of broken
CSS selectors, return a JSON object with the fixed selectors.

For each broken selector, output:
  {{
    "name": "field_name_from_input",
    "selector": "the new CSS selector that should match the same data",
    "reason": "one sentence explaining the fix"
  }}

Only output fields where you are confident the new selector works.
If a field can't be fixed confidently, omit it from the output.

Input fields (may be broken):
{fields}

HTML:
{html}

Output ONLY a JSON object: {{"fixes": [...]}}
"""


def _heal_schema(
    broken: Schema,  # type: ignore[name-defined]  # noqa: F821
    html: str,
    *,
    llm_model: str = "gpt-4o-mini",
) -> Schema:  # type: ignore[name-defined]  # noqa: F821
    """Ask an LLM to patch a broken schema.

    Parameters
    ----------
    broken:
        The :class:`Schema` with selectors that no longer work.
    html:
        The current HTML of the page. Cleaned internally before
        sending to the LLM (HTML noise is stripped).
    llm_model:
        litellm model string. Default ``"gpt-4o-mini"`` (cheap).

    Returns:
    -------
    Schema
        A new :class:`Schema` with patched selectors. The original
        ``broken`` schema is untouched. Fields the LLM couldn't fix
        retain their original selectors.

    Raises:
    ------
    ConfigurationError:
        If the LLM call fails, returns non-JSON, or returns an
        invalid shape.
    """
    from scrapex.models import FieldSpec, Schema
    from scrapex.schema_synth import _get_litellm

    if not broken.fields:
        # Trivial: nothing to fix. Return a copy.
        return broken.model_copy(deep=True)

    cleaned_html = clean_html_for_llm(html)
    fields_json = json.dumps(
        [
            {"name": f.name, "selector": f.selector, "attr": f.attr}
            for f in broken.fields
        ],
        indent=2,
    )
    prompt = _PROMPT.format(fields=fields_json, html=cleaned_html)

    litellm = _get_litellm()
    try:
        resp = litellm.completion(
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as e:
        raise ConfigurationError(
            f"Schema.heal() failed to call {llm_model!r}: {e}. "
            f"Check the model name and API key."
        ) from e

    text = resp.choices[0].message.content or ""
    if not text.strip():
        raise ConfigurationError(
            f"Schema.heal() got empty response from {llm_model!r}. "
            f"The model may have refused."
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"Schema.heal() returned non-JSON: {text[:200]!r}"
        ) from e

    if not isinstance(data, dict) or "fixes" not in data:
        raise ConfigurationError(
            f"Schema.heal() response missing 'fixes' key: {text[:200]!r}"
        )

    fixes = data["fixes"]
    if not isinstance(fixes, list):
        raise ConfigurationError(
            f"Schema.heal() 'fixes' is not a list: {type(fixes).__name__}"
        )

    # Build a name -> new selector map from valid fixes only.
    new_selectors: dict[str, str] = {}
    new_reasons: dict[str, str] = {}
    for entry in fixes:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        selector = entry.get("selector")
        if not isinstance(name, str) or not isinstance(selector, str):
            continue
        if not selector.strip():
            continue
        new_selectors[name] = selector
        new_reasons[name] = str(entry.get("reason", ""))

    # Patch the fields: replace selector if we got a fix, else keep original.
    new_fields: list[FieldSpec] = []
    for f in broken.fields:
        if f.name in new_selectors:
            new_fields.append(
                FieldSpec(
                    name=f.name,
                    selector=new_selectors[f.name],
                    attr=f.attr,
                    description=(
                        f"healed: {new_reasons[f.name]}"
                        if new_reasons.get(f.name)
                        else f.description
                    ),
                )
            )
        else:
            new_fields.append(f.model_copy())

    return Schema(
        strategy=broken.strategy,
        fields=new_fields,
    )


__all__ = ["_heal_schema"]
