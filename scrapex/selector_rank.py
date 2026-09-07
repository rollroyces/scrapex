"""Selector ranking helper for LLM-driven extraction.

WARNING: This module was added as a SPECULATIVE feature — built
before the SRPE probe ran for real. If the probe shows browser-use
handles selectors on its own, this is over-engineered. Re-evaluate
after spike 006 measures a real failure mode.

What it does:
- Takes an HTML page + a natural-language hint ("register of transactions")
- Returns the top-N CSS selectors ranked by how likely they are to
  match what the hint describes
- Uses an LLM under the hood (litellm), but only ONE call per page

Why this might help:
- When browser-use gets stuck on a page with many similar-looking
  links ("download", "view", "register"), an extra ranking pass
  gives it pre-vetted options
- When the LLM is uncertain, ranked candidates reduce the search space

Why this might NOT help:
- browser-use's own LLM already ranks selectors when it tries each
- Two LLMs ranking separately is more expensive AND may disagree
- The extra LLM call adds latency and tokens

Design rules (so this stays opt-in and cheap):
- Opt-in only: nothing changes unless the user calls rank_selectors
- One LLM call per page (not per candidate)
- Returns top-3 by default (capped, not unbounded)
- No module-level caching: callers can cache at their layer if needed.
  LRU-caching here would hold the cleaned HTML in memory which is
  larger than the prompt template; callers know their own reuse pattern.
"""
from __future__ import annotations

import json
from typing import Any

from scrapex.errors import ConfigurationError
from scrapex.html_clean import clean_html_for_llm

_PROMPT = """\
You are a selector ranker. Given an HTML page and a description of
what to find, return the top {top_k} CSS selectors most likely to
match.

Description: {hint}

HTML:
{html}

Output ONLY a JSON object:
{{"selectors": [
  {{"selector": "css.selector.here", "score": 0.0-1.0, "reason": "why"}},
  ...
]}}

Score 1.0 = certain match. 0.0 = certain miss. Order by score desc.
Only return selectors that actually exist in the HTML.
"""


def _rank_selectors(
    html: str,
    hint: str,
    *,
    llm_model: str = "gpt-4o-mini",
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Rank the top CSS selectors that match a natural-language hint.

    Parameters
    ----------
    html:
        The HTML to analyze. Cleaned before sending to the LLM.

    Hint:
        Natural-language description of what to find. Examples:
        "the register of transactions link"
        "the price table"
        "the submit button for the disclaimer"
    llm_model:
        litellm model string. Default ``gpt-4o-mini`` (cheap).
    top_k:
        Number of selectors to return. Default 3.

    Returns:
    -------
    list[dict]
        Each dict has ``selector`` (str), ``score`` (float 0.0-1.0),
        and ``reason`` (str). Sorted by score descending.

    Raises:
    ------
    ConfigurationError:
        If the LLM call fails or returns non-JSON.
    """
    from scrapex.schema_synth import _get_litellm

    cleaned = clean_html_for_llm(html)
    litellm = _get_litellm()
    prompt = _PROMPT.format(hint=hint, html=cleaned, top_k=top_k)

    try:
        resp = litellm.completion(
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as e:
        raise ConfigurationError(
            f"rank_selectors() failed to call {llm_model!r}: {e}. "
            f"Check the model name and API key."
        ) from e

    text = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"LLM returned non-JSON: {text[:200]!r}"
        ) from e

    if not isinstance(data, dict) or "selectors" not in data:
        raise ConfigurationError(
            f"LLM response missing 'selectors' key: {text[:200]!r}"
        )

    selectors = data["selectors"]
    if not isinstance(selectors, list):
        raise ConfigurationError(f"LLM 'selectors' is not a list: {type(selectors).__name__}")

    # Validate each entry has at minimum a selector string
    validated: list[dict[str, Any]] = []
    for entry in selectors:
        if not isinstance(entry, dict):
            continue
        sel = entry.get("selector")
        if not isinstance(sel, str) or not sel:
            continue
        validated.append(
            {
                "selector": sel,
                "score": float(entry.get("score", 0.0)),
                "reason": str(entry.get("reason", "")),
            }
        )

    # Sort by score desc, cap at top_k
    validated.sort(key=lambda x: x["score"], reverse=True)
    return validated[:top_k]


__all__ = ["_rank_selectors"]
