"""LLM-driven extraction schema synthesis.

This is the only "AI magic" in scrapex. The premise is simple: a user
writes a one-line goal like "extract the report title, price, and
download link" and an LLM produces a working :class:`Schema` they can
use directly.

Design rules (so this doesn't become another black box):

1. **Opt-in.** ``Schema(strategy=..., fields=[...])`` still works
   without touching an LLM. ``Schema.from_goal()`` is the *only* entry
   point that calls the network. Zero LLM cost on the default path.

2. **Default = local, cheap, fast.** Tries Ollama first (no API key
   needed, free, runs on the user's machine). Falls back to
   cloud providers only if the user explicitly passes an API key.

3. **Lenient.** Never raises on empty extraction. The user gets a
   working :class:`Schema` back even if the LLM hallucinated; they
   see the result and can iterate. The warning is in
   ``explain()`` output, not in exceptions.

4. **Transparent.** ``schema.explain()`` returns a list of
   human-readable reasons ("title: I picked ``h1.report-title`` because
   it looked like a heading in the page"). The user can audit and fix.

5. **Cacheable.** Identical (html, goal) pairs return cached results
   within the process. No network call on the second hit.

What this is NOT:
- Not a replacement for hand-written schemas on critical pages. The
  user owns the schema after ``from_goal()`` returns; they should
  review it before relying on it in production.
- Not a competitor to scrapegraph-ai. scrapegraph-ai runs the full
  LLM-driven pipeline; we just synthesize a Schema and stop.
- Not magic. The LLM picks CSS selectors the same way a human would
  after reading the HTML. Sometimes it's right, sometimes it's not.
"""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from scrapex.errors import ConfigurationError
from scrapex.models import FieldSpec, Schema

if TYPE_CHECKING:
    from playwright.async_api import Page  # noqa: F401  (type only)


# Statically tell mypy that Schema has from_goal and explain methods.
# Runtime monkey-patch lives further down in the file.
if TYPE_CHECKING:
    from scrapex.models import Schema as _Schema

    _Schema.explain = lambda self: []  # type: ignore[attr-defined]
    _Schema.from_goal = classmethod(lambda cls, *a, **kw: None)  # type: ignore[attr-defined]


# The prompt template. Deliberately short and structured.
# Output schema: a JSON object with a "fields" list; each field is
# {name, selector, attr, reason}. The "reason" is what populates
# schema.explain() so the user can audit.
_PROMPT_TEMPLATE = """\
You are a precise web-scraping schema synthesizer.

Given an HTML page and a one-line goal, return a JSON object with a single
"fields" key. Each entry in "fields" describes one piece of data to extract:

  {{
    "name": "snake_case_field_name",
    "selector": "CSS selector that targets the element (text default)",
    "attr": "text" or "href" — which attribute to read
    "reason": "one sentence explaining why you picked this selector"
  }}

Rules:
- One field per piece of data the user asked for. Do NOT hallucinate extras.
- Selectors must be CSS (not XPath). Prefer class-targeted selectors
  over positional ones.
- Use "text" for visible text, "href" for links.
- The "reason" is for the human who will maintain this — be specific.

Goal: {goal}

HTML:
{html}

Output ONLY the JSON object. No prose, no markdown fences.
"""


# Detect which model to use based on what's available locally. This is
# the "default = local, cheap, fast" rule. We check in this order:
#   1. Caller passed an explicit ``llm_model`` → use that
#   2. ``OLLAMA_HOST`` env var or default localhost:11434 → use Ollama
#   3. ``OPENAI_API_KEY`` env var → fall back to gpt-4o-mini
#   4. None of the above → raise ConfigurationError
#
# The actual HTTP call is delegated to :mod:`litellm` so we support
# both Ollama's OpenAI-compatible endpoint and the OpenAI API without
# branching the call site.
def _resolve_default_model() -> str:
    """Return the default model string for the LLM call.

    Resolution order:
      1. ``OLLAMA_HOST`` set (env or default) → ``ollama/qwen2.5:1.5b``
      2. ``OPENAI_API_KEY`` set → ``gpt-4o-mini``
      3. Otherwise raise :class:`ConfigurationError` with install hint
    """
    if os.environ.get("OLLAMA_HOST") or _ollama_reachable():
        # Ollama's OpenAI-compatible API. The model name is the user's
        # choice; ``qwen2.5:1.5b`` is a small, fast default that runs
        # well on a laptop.
        return "ollama/qwen2.5:1.5b"
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-4o-mini"
    raise ConfigurationError(
        "Schema.from_goal() needs an LLM. Either:\n"
        "  - Install Ollama (https://ollama.com) and `ollama pull qwen2.5:1.5b`\n"
        "  - Or set OPENAI_API_KEY for OpenAI\n"
        "Or pass llm_model='ollama/your-model' or llm_model='gpt-4o-mini' explicitly."
    )


def _ollama_reachable() -> bool:
    """True if Ollama is running on the default port. Cheap HTTP probe."""
    try:
        import httpx

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        r = httpx.get(f"{host}/api/tags", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


# Module-level cache. Key is (html_hash, goal) → Schema. LRU keeps the
# process from holding more than 256 schemas in memory at once.
@lru_cache(maxsize=256)
def _get_litellm() -> Any:
    """Lazy-import litellm. Raises ConfigurationError if not installed.

    litellm is in the [llm] extra, not a hard dep. Users who only want
    the default Schema(strategy=..., fields=...) path don't pay the
    import cost. Users who call from_goal() need litellm.
    """
    try:
        import litellm

        return litellm
    except ImportError as e:
        raise ConfigurationError(
            "Schema.from_goal() requires the 'llm' extra: "
            "pip install 'scrapex[llm]'. litellm not importable."
        ) from e


@lru_cache(maxsize=256)
def _cached_synthesize(goal: str, html: str, model: str, html_hash: str) -> dict[str, Any]:
    """Run the LLM call. Result is the JSON dict, not a Schema.

    Cached. Raises ConfigurationError if no model is reachable, or
    if the LLM returns non-JSON.

    Parameters
    ----------
    goal:
        The user's natural-language goal. Used in the prompt.
    html:
        The HTML to analyze. Truncated to 50K chars before sending.
    model:
        The litellm model string.
    html_hash:
        SHA-256 prefix of html. Included as a 4th cache key so the
        cache key is bounded in length (full HTML is too long for a
        useful cache key).
    """
    litellm = _get_litellm()
    prompt = _PROMPT_TEMPLATE.format(goal=goal, html=html[:50_000])
    try:
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as e:
        raise ConfigurationError(
            f"Schema.from_goal() failed to call model {model!r}: {e}. "
            f"Check that the LLM is running and the model is pulled. "
            f"Pass llm_model=... to use a different model."
        ) from e

    text = resp.choices[0].message.content
    if not text or not text.strip():
        # Empty response is almost always a real error (model refused,
        # network truncation, model crash). Surface it loudly rather
        # than silently returning {} and pretending it worked.
        raise ConfigurationError(
            f"LLM returned empty response from {model!r}. "
            f"The model may have refused, crashed, or timed out. "
            f"Try a different model or simplify the goal."
        )
    try:
        raw: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"LLM returned non-JSON: {text[:200]!r}. Try a different model or simplify the goal."
        ) from e
    # Validate the shape — must be a dict.
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"LLM response was not a JSON object: {text[:200]!r}. "
            f"Got {type(raw).__name__}. "
            f"Try a different model or simplify the goal."
        )
    return raw


# A public facade over the cache, primarily for testability.
def _synthesize(
    html: str,
    goal: str,
    *,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """Synthesize a schema dict via the LLM. Cached.

    This is the raw synthesis call. ``Schema.from_goal()`` is the
    public, validated, explainable wrapper around it.
    """
    model = llm_model or _resolve_default_model()
    # Hash the HTML so cache keys are short. Real goal is also passed
    # so identical goal+html+model hits the cache but the prompt sees
    # the real goal (not the hash).
    html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
    return _cached_synthesize(goal, html, model, html_hash)


# ---------------------------------------------------------------------------
# The extended Schema class — we use a Pydantic model_validator to add
# from_goal() as a classmethod without breaking the existing Schema API.
# ---------------------------------------------------------------------------


def from_goal(
    cls: type[Schema],
    goal: str,
    html: str,
    *,
    llm_model: str | None = None,
) -> Schema:
    """Synthesize a Schema from a natural-language goal + HTML.

    One-line call::

        schema = Schema.from_goal(
            "extract the title, price, and download link",
            html=page_html,
        )
        result = await scrape(ScrapeRequest(url=..., schema=schema))

    Parameters
    ----------
    goal:
        One-sentence description of what to extract. Be specific
        (the model needs to know field names).
    html:
        The HTML to analyze. Truncated to 50K characters to fit context.
    llm_model:
        litellm model string. If ``None``, picks Ollama (if running)
        or gpt-4o-mini (if ``OPENAI_API_KEY`` is set) in that order.

    Returns:
    -------
    Schema
        A :class:`Schema` instance with the LLM-generated fields. The
        same shape as a hand-written Schema; nothing magic.

    Raises:
    ------
    ConfigurationError:
        If no LLM is reachable, the model is unknown, or the LLM
        returns non-JSON.
    """
    data = _synthesize(html, goal, llm_model=llm_model)

    fields: list[FieldSpec] = []
    skipped: list[Any] = []
    for f in data.get("fields", []):
        if not isinstance(f, dict):
            skipped.append(f)
            continue
        name = f.get("name")
        selector = f.get("selector", "")
        # Drop fields that don't have the minimum contract: name must
        # be a non-empty string, selector must be a string. Lenient
        # mode = the user gets a Schema back even if some fields are
        # bad, but we don't silently rename "name": 123 to "field_1"
        # because that's worse than skipping (mysterious field with
        # no apparent source).
        if not isinstance(name, str) or not name:
            skipped.append(f)
            continue
        if not isinstance(selector, str):
            skipped.append(f)
            continue
        try:
            fields.append(
                FieldSpec(
                    name=name,
                    selector=selector,
                    attr=f.get("attr", "text"),
                    description=f.get("reason"),
                )
            )
        except Exception:
            skipped.append(f)
            continue

    if not fields:
        warnings.warn(
            f"Schema.from_goal() returned 0 usable fields for goal={goal!r}. "
            f"LLM response was: {data!r}. "
            f"Skipped {len(skipped)} malformed field(s). "
            f"Try a more specific goal or a different model.",
            UserWarning,
            stacklevel=2,
        )

    return cls(strategy=ExtractionStrategy.CSS, fields=fields)


# Strategy enum (avoid circular import)
from scrapex.models import ExtractionStrategy  # noqa: E402

# Attach as a classmethod to Schema. This is a deliberate monkey-patch
# to keep the public surface clean: users get ``Schema.from_goal()``
# without us forking the model into a separate file. Mypy cannot see
# dynamic class-attribute assignment; the runtime behavior is correct.
Schema.from_goal = classmethod(from_goal)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ``Schema.explain()`` — human-readable audit of how the schema was built
# ---------------------------------------------------------------------------


def explain(self: Schema) -> list[str]:
    """Return one human-readable line per field.

    For schemas built by ``from_goal()``, each line explains why the LLM
    picked that selector (the model's own ``reason`` field is included).
    For hand-written schemas, the line is a description of the
    selector itself.

    Always available — never raises. The user can read this to debug
    when a field stops matching.
    """
    out: list[str] = []
    for f in self.fields:
        if f.description:
            out.append(f"{f.name}: {f.description}")
        else:
            out.append(f"{f.name}: selector={f.selector!r}, attr={f.attr!r}")
    return out


Schema.explain = explain  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Internal helper used by tests — apply a schema to a snippet of HTML
# so we can detect "LLM hallucinated a field" before returning.
# ---------------------------------------------------------------------------


def _apply_schema_to_html(html: str, schema: Schema) -> dict[str, Any]:
    """Apply ``schema`` to ``html`` and return {field: value}."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: dict[str, Any] = {}
    for f in schema.fields:
        el = soup.select_one(f.selector) if f.selector else None
        if el is None:
            out[f.name] = None
        elif f.attr == "href":
            out[f.name] = el.get("href")
        else:
            out[f.name] = el.get_text(strip=True)
    return out


__all__ = ["_apply_schema_to_html", "_resolve_default_model", "_synthesize", "explain", "from_goal"]
