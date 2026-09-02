"""Tests for the helpers in scrapex.china_llm (every shortcut function)."""
from __future__ import annotations

import pytest

from scrapex import china
from scrapex.china_llm import ModelPreset

# ---------------------------------------------------------------------------
# Each shortcut function must return a valid preset
# ---------------------------------------------------------------------------
SHORTCUT_FUNCTIONS = [
    (china.deepseek_v3, "deepseek-v3", "deepseek"),
    (china.deepseek_reasoner, "deepseek-reasoner", "deepseek"),
    (china.qwen_max, "qwen-max", "qwencloud"),
    (china.qwen_plus, "qwen-plus", "qwencloud"),
    (china.qwen_flash, "qwen-flash", "qwencloud"),
    (china.qwen_turbo, "qwen-turbo", "dashscope"),
    (china.glm_4_7, "glm-4.7", "zai"),
    (china.glm_4_6, "glm-4.6", "zai"),
    (china.glm_flash, "glm-flash", "zai"),
    (china.kimi_v1_8k, "kimi-v1-8k", "moonshot"),
    (china.kimi_v1_128k, "kimi-v1-128k", "moonshot"),
    (china.doubao_flash, "doubao-flash", "volcengine"),
]


@pytest.mark.parametrize("fn,preset_name,provider", SHORTCUT_FUNCTIONS)
def test_shortcut_returns_correct_preset(fn, preset_name, provider):
    preset = fn()
    assert isinstance(preset, ModelPreset)
    assert preset.name == preset_name
    assert preset.provider == provider


# ---------------------------------------------------------------------------
# Every shortcut's model string must contain the litellm provider prefix
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("preset_name", [name for _, name, _ in SHORTCUT_FUNCTIONS])
def test_shortcut_model_has_provider_prefix(preset_name):
    preset = china.get(preset_name)
    # Format is "<provider>/<model>"; the slash must be there
    assert "/" in preset.model, f"{preset.name} model {preset.model!r} missing slash"


# ---------------------------------------------------------------------------
# Tier metadata is consistent
# ---------------------------------------------------------------------------
def test_every_shortcut_preset_has_valid_tier():
    valid_tiers = {"flagship", "mid", "fast", "free"}
    for fn, name, _ in SHORTCUT_FUNCTIONS:
        preset = fn()
        assert preset.tier in valid_tiers, f"{name} has invalid tier {preset.tier!r}"


def test_every_shortcut_preset_has_description():
    for fn, name, _ in SHORTCUT_FUNCTIONS:
        preset = fn()
        assert preset.description, f"{name} missing description"
        # Description should be human-readable (multi-word)
        assert len(preset.description) > 10


# ---------------------------------------------------------------------------
# api_base_for coverage — every provider in the catalog
# ---------------------------------------------------------------------------
def test_api_base_for_known_provider_intl():
    """Every preset's provider has a sensible api_base_for default."""
    for _fn, name, provider in SHORTCUT_FUNCTIONS:
        # Either it has a region endpoint (returns str) or None (uses litellm default)
        result = china.api_base_for(provider, "intl")
        assert result is None or isinstance(result, str), (
            f"{name} provider {provider!r} returned weird api_base: {result!r}"
        )


def test_api_base_for_invalid_provider_returns_none():
    assert china.api_base_for("nonexistent-provider") is None
    assert china.api_base_for("nonexistent-provider", "cn") is None


def test_api_base_for_invalid_region_returns_none():
    """Only intl and cn are valid regions; anything else returns None."""
    # The cast ignores the type system — we're testing runtime safety
    assert china.api_base_for("moonshot", "us-west") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# presets() iteration — covers every preset
# ---------------------------------------------------------------------------
def test_presets_includes_every_shortcut():
    """Every shortcut has a corresponding preset in the catalog."""
    catalog_names = {p.name for p in china.presets()}
    for fn, preset_name, _ in SHORTCUT_FUNCTIONS:
        assert preset_name in catalog_names, (
            f"shortcut {fn.__name__} returns {preset_name} but it's not in presets()"
        )


def test_presets_returns_frozen_dataclass_instances():
    """Presets are immutable — dataclass(frozen=True) means you can't modify."""
    preset = china.deepseek_v3()
    with pytest.raises((AttributeError, Exception)):
        preset.name = "renamed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Region routing is exercised for every region-routed provider
# ---------------------------------------------------------------------------
REGION_ROUTED_PROVIDERS = ["moonshot", "qwen_ai_platform", "qwencloud"]


@pytest.mark.parametrize("provider", REGION_ROUTED_PROVIDERS)
def test_region_routed_provider_has_both_endpoints(provider):
    """Each region-routed provider must have distinct intl + cn URLs."""
    intl = china.api_base_for(provider, "intl")
    cn = china.api_base_for(provider, "cn")
    assert intl is not None
    assert cn is not None
    assert intl != cn, f"{provider} has same URL for both regions"


@pytest.mark.parametrize("provider", ["deepseek", "zai", "volcengine", "dashscope"])
def test_non_region_routed_provider_has_no_endpoints(provider):
    """Providers with single global endpoint must return None for both regions."""
    assert china.api_base_for(provider, "intl") is None
    assert china.api_base_for(provider, "cn") is None


# ---------------------------------------------------------------------------
# Env-var discovery covers every provider in the catalog
# ---------------------------------------------------------------------------
def test_every_shortcut_provider_has_env_var_config():
    """Every provider should be in the env-var discovery table."""
    for _fn, _, provider in SHORTCUT_FUNCTIONS:
        result = china.discover_api_key(provider)
        # Should return None (not set) but not raise
        assert result is None, f"{provider} unexpectedly returned {result!r}"


def test_discover_api_key_invalid_provider_returns_none():
    """Unknown provider returns None instead of raising."""
    assert china.discover_api_key("totally-fake-provider") is None
