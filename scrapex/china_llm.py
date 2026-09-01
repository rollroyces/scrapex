"""Curated presets for China-hosted LLM providers.

scrapex uses :mod:`litellm` under the hood for LLM calls, so any litellm-supported
model works. This module adds three things on top of litellm:

1. **Short, memorable preset names** — ``china.deepseek_v3()`` instead of
   remembering the litellm string ``"deepseek/deepseek-chat"``.
2. **Region routing** — auto-pick ``api_base`` between international (``.com``)
   and mainland China (``.cn``) endpoints. Users in mainland China shouldn't
   have to manually set ``MOONSHOT_API_BASE``.
3. **Env-var discovery** — scan the right env var(s) for each provider
   automatically and pick whichever is set.

Excluded by design (not verified against current litellm or not stable):
    - Baidu Wenxin / ERNIE — uses Baidu Qianfan, separate litellm integration,
      not in canonical litellm provider list as of 2026-09
    - Hunyuan, Spark, MiniMax — provider-specific quirks; add when verified

All preset model strings below are taken from the live litellm docs
(verified 2026-09-01). If a model is deprecated upstream, litellm will
raise at call time — we surface that error directly rather than masking it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Region routing
# ---------------------------------------------------------------------------
Region = Literal["intl", "cn"]


# Endpoint overrides — provider: region → api_base URL.
# Only providers with separate China/international endpoints are listed.
_REGION_API_BASES: dict[str, dict[Region, str]] = {
    "moonshot": {
        "intl": "https://api.moonshot.ai/v1",
        "cn": "https://api.moonshot.cn/v1",
    },
    "qwen_ai_platform": {  # mainland China variant of DashScope/Qwen
        "intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "qwencloud": {  # international Qwen (canonical international brand)
        "intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
}


# ---------------------------------------------------------------------------
# Env-var discovery per provider
# ---------------------------------------------------------------------------
# Each provider has 1+ env vars it reads, in priority order. First match wins.
_PROVIDER_ENV_VARS: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "qwen": ("QWENCLOUD_API_KEY", "QWEN_AI_PLATFORM_API_KEY", "DASHSCOPE_API_KEY"),
    "qwen_ai_platform": ("QWEN_AI_PLATFORM_API_KEY", "DASHSCOPE_API_KEY"),
    "qwencloud": ("QWENCLOUD_API_KEY", "DASHSCOPE_API_KEY"),
    "dashscope": ("DASHSCOPE_API_KEY",),
    "zai": ("ZAI_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY",),
    "volcengine": ("VOLCENGINE_API_KEY", "ARK_API_KEY"),
}


# ---------------------------------------------------------------------------
# Preset catalog
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ModelPreset:
    """One preset: the litellm model string + provider it routes through."""

    name: str  # canonical short name (e.g. "deepseek-v3")
    model: str  # litellm model string (e.g. "deepseek/deepseek-chat")
    provider: str  # litellm provider key (e.g. "deepseek")
    description: str  # human-readable
    tier: Literal["flagship", "mid", "fast", "free"]  # cost/quality bucket
    context_window: int | None = None  # tokens, if known


# Curated presets — verified against litellm docs 2026-09-01.
_PRESETS: dict[str, ModelPreset] = {
    # DeepSeek
    "deepseek-v3": ModelPreset(
        name="deepseek-v3",
        model="deepseek/deepseek-chat",
        provider="deepseek",
        description="DeepSeek V3 — strong general-purpose, cheap",
        tier="mid",
        context_window=64_000,
    ),
    "deepseek-reasoner": ModelPreset(
        name="deepseek-reasoner",
        model="deepseek/deepseek-reasoner",
        provider="deepseek",
        description="DeepSeek reasoner — chain-of-thought, slower but more accurate",
        tier="mid",
        context_window=64_000,
    ),
    # Qwen / DashScope
    "qwen-max": ModelPreset(
        name="qwen-max",
        model="qwencloud/qwen-max",
        provider="qwencloud",
        description="Qwen Max — Alibaba flagship",
        tier="flagship",
    ),
    "qwen-plus": ModelPreset(
        name="qwen-plus",
        model="qwencloud/qwen-plus",
        provider="qwencloud",
        description="Qwen Plus — balanced cost/quality",
        tier="mid",
    ),
    "qwen-flash": ModelPreset(
        name="qwen-flash",
        model="qwencloud/qwen-flash",
        provider="qwencloud",
        description="Qwen Flash — fast and cheap, good for high-volume scraping",
        tier="fast",
    ),
    "qwen-turbo": ModelPreset(
        name="qwen-turbo",
        model="dashscope/qwen-turbo",
        provider="dashscope",
        description="Qwen Turbo (legacy DashScope prefix) — fast and cheap",
        tier="fast",
    ),
    # Zhipu GLM (Z.AI)
    "glm-4.7": ModelPreset(
        name="glm-4.7",
        model="zai/glm-4.7",
        provider="zai",
        description="Zhipu GLM-4.7 — 200K context, reasoning",
        tier="flagship",
        context_window=200_000,
    ),
    "glm-4.6": ModelPreset(
        name="glm-4.6",
        model="zai/glm-4.6",
        provider="zai",
        description="Zhipu GLM-4.6 — 200K context",
        tier="mid",
        context_window=200_000,
    ),
    "glm-flash": ModelPreset(
        name="glm-flash",
        model="zai/glm-4.5-flash",
        provider="zai",
        description="Zhipu GLM-4.5-Flash — free tier",
        tier="free",
        context_window=128_000,
    ),
    # Moonshot / Kimi
    "kimi-v1-8k": ModelPreset(
        name="kimi-v1-8k",
        model="moonshot/moonshot-v1-8k",
        provider="moonshot",
        description="Moonshot v1 8K — short context, cheap",
        tier="fast",
        context_window=8_000,
    ),
    "kimi-v1-128k": ModelPreset(
        name="kimi-v1-128k",
        model="moonshot/moonshot-v1-128k",
        provider="moonshot",
        description="Moonshot v1 128K — long context, good for big pages",
        tier="mid",
        context_window=128_000,
    ),
    # Volcengine / Doubao
    "doubao-flash": ModelPreset(
        name="doubao-flash",
        model="volcengine/doubao-seed-1-6-flash-250715",
        provider="volcengine",
        description="Doubao Seed 1.6 Flash — ByteDance fast model",
        tier="fast",
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def presets() -> list[ModelPreset]:
    """All known presets, sorted by tier (flagship → free) then name."""
    tier_order = {"flagship": 0, "mid": 1, "fast": 2, "free": 3}
    return sorted(
        _PRESETS.values(),
        key=lambda p: (tier_order.get(p.tier, 99), p.name),
    )


def get(name: str) -> ModelPreset:
    """Look up a preset by its short name.

    >>> china.get("deepseek-v3").model
    'deepseek/deepseek-chat'
    """
    if name not in _PRESETS:
        raise KeyError(
            f"Unknown preset '{name}'. Available: {sorted(_PRESETS)}"
        )
    return _PRESETS[name]


def discover_api_key(provider: str) -> str | None:
    """Find the API key for ``provider`` by scanning its known env vars.

    Returns the first set value, or ``None`` if none are set. Does NOT
    raise — callers decide whether a missing key is an error.
    """
    for var in _PROVIDER_ENV_VARS.get(provider, ()):
        value = os.environ.get(var)
        if value:
            return value
    return None


def api_base_for(provider: str, region: Region = "intl") -> str | None:
    """Pick the right ``api_base`` URL for ``provider`` and ``region``.

    Returns ``None`` for providers that don't have region-specific endpoints
    (use litellm's built-in default).
    """
    bases = _REGION_API_BASES.get(provider, {})
    return bases.get(region)


def resolve(
    preset_name: str,
    *,
    region: Region = "intl",
    api_key: str | None = None,
) -> dict[str, str]:
    """Resolve a preset to the kwargs needed for litellm.acompletion().

    This is what :class:`ScrapeRequest` calls internally when given a
    China preset name. Returns a dict suitable for ``**`` unpacking.

    Parameters
    ----------
    preset_name:
        Short preset name (see :func:`presets`).
    region:
        ``"intl"`` for international endpoints, ``"cn"`` for mainland China.
    api_key:
        Explicit key — if ``None``, falls back to :func:`discover_api_key`.

    Returns
    -------
    dict with keys ``model``, ``api_key``, and optionally ``api_base``.

    Raises
    ------
    KeyError:
        If ``preset_name`` is not a known preset.
    ConfigurationError:
        If no API key can be found.
    """
    from scrapex.errors import ConfigurationError

    preset = get(preset_name)
    key = api_key or discover_api_key(preset.provider)
    if not key:
        env_vars = _PROVIDER_ENV_VARS.get(preset.provider, ())
        raise ConfigurationError(
            f"No API key found for provider '{preset.provider}'. "
            f"Set one of: {', '.join(env_vars)}"
        )
    out: dict[str, str] = {"model": preset.model, "api_key": key}
    base = api_base_for(preset.provider, region)
    if base:
        out["api_base"] = base
    return out


# Curated short-name helpers — import as ``from scrapex.china_llm import deepseek_v3``
# or use ``china.deepseek_v3()`` (lowercase). Returns ModelPreset.
def deepseek_v3() -> ModelPreset:
    """DeepSeek V3 preset."""
    return get("deepseek-v3")


def deepseek_reasoner() -> ModelPreset:
    """DeepSeek reasoner preset."""
    return get("deepseek-reasoner")


def qwen_max() -> ModelPreset:
    """Qwen Max preset."""
    return get("qwen-max")


def qwen_plus() -> ModelPreset:
    """Qwen Plus preset."""
    return get("qwen-plus")


def qwen_flash() -> ModelPreset:
    """Qwen Flash preset."""
    return get("qwen-flash")


def qwen_turbo() -> ModelPreset:
    """Qwen Turbo (legacy DashScope prefix) preset."""
    return get("qwen-turbo")


def glm_4_7() -> ModelPreset:
    """Zhipu GLM-4.7 preset."""
    return get("glm-4.7")


def glm_4_6() -> ModelPreset:
    """Zhipu GLM-4.6 preset."""
    return get("glm-4.6")


def glm_flash() -> ModelPreset:
    """Zhipu GLM-4.5-Flash (free tier) preset."""
    return get("glm-flash")


def kimi_v1_8k() -> ModelPreset:
    """Moonshot v1 8K preset."""
    return get("kimi-v1-8k")


def kimi_v1_128k() -> ModelPreset:
    """Moonshot v1 128K preset."""
    return get("kimi-v1-128k")


def doubao_flash() -> ModelPreset:
    """Doubao Seed 1.6 Flash preset."""
    return get("doubao-flash")


__all__ = [
    "ModelPreset",
    "Region",
    "api_base_for",
    "deepseek_reasoner",
    "deepseek_v3",
    "discover_api_key",
    "doubao_flash",
    "get",
    "glm_4_6",
    "glm_4_7",
    "glm_flash",
    "kimi_v1_8k",
    "kimi_v1_128k",
    "presets",
    "qwen_flash",
    "qwen_max",
    "qwen_plus",
    "qwen_turbo",
    "resolve",
]
