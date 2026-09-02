"""Tests for scrapex.china_llm — curated China-hosted LLM presets.

These tests lock in:
- Preset catalog contents (catch upstream renames / typos)
- Region routing (mainland China vs international endpoints)
- Env-var discovery (each provider's known vars)
- Resolution behavior (preset name → litellm kwargs)
- Error cases (unknown preset, missing API key)
"""

from __future__ import annotations

import pytest

from scrapex import china as china_llm
from scrapex.errors import ConfigurationError


# ---------------------------------------------------------------------------
# Preset catalog
# ---------------------------------------------------------------------------
def test_presets_returns_non_empty_sorted_list():
    presets = china_llm.presets()
    assert len(presets) >= 5, "catalog should cover at least 5 China providers"
    # Sorted: flagship tier first
    tiers_in_order = [p.tier for p in presets]
    seen_tiers = set(tiers_in_order)
    # At least one flagship and one non-flagship tier exist
    assert "flagship" in seen_tiers


def test_every_preset_has_litellm_model_string():
    """No preset may have an empty model string — would fail at litellm call time."""
    for p in china_llm.presets():
        assert p.model, f"{p.name} has empty model string"
        assert "/" in p.model, f"{p.name} model {p.model!r} missing litellm provider prefix"


def test_every_preset_has_provider_in_supported_list():
    """Defends against typos in the provider field."""
    known_providers = {
        "deepseek",
        "qwencloud",
        "dashscope",
        "qwen_ai_platform",
        "zai",
        "moonshot",
        "volcengine",
    }
    for p in china_llm.presets():
        assert p.provider in known_providers, f"{p.name}: provider {p.provider!r} not in known list"


@pytest.mark.parametrize(
    "preset_name,expected_model",
    [
        ("deepseek-v3", "deepseek/deepseek-chat"),
        ("deepseek-reasoner", "deepseek/deepseek-reasoner"),
        ("qwen-max", "qwencloud/qwen-max"),
        ("qwen-plus", "qwencloud/qwen-plus"),
        ("qwen-flash", "qwencloud/qwen-flash"),
        ("qwen-turbo", "dashscope/qwen-turbo"),
        ("glm-4.7", "zai/glm-4.7"),
        ("glm-4.6", "zai/glm-4.6"),
        ("glm-flash", "zai/glm-4.5-flash"),
        ("kimi-v1-8k", "moonshot/moonshot-v1-8k"),
        ("kimi-v1-128k", "moonshot/moonshot-v1-128k"),
        ("doubao-flash", "volcengine/doubao-seed-1-6-flash-250715"),
    ],
)
def test_preset_model_strings(preset_name, expected_model):
    """Pin exact litellm model strings — catches upstream renames."""
    assert china_llm.get(preset_name).model == expected_model


# ---------------------------------------------------------------------------
# Region routing
# ---------------------------------------------------------------------------
def test_moonshot_routes_cn_to_cn_endpoint():
    """Moonshot has a real .cn endpoint for mainland China."""
    assert china_llm.api_base_for("moonshot", "cn") == "https://api.moonshot.cn/v1"


def test_moonshot_routes_intl_to_ai_endpoint():
    assert china_llm.api_base_for("moonshot", "intl") == "https://api.moonshot.ai/v1"


def test_qwen_routes_cn_to_aliyun_mainland():
    assert china_llm.api_base_for("qwen_ai_platform", "cn") == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_qwen_routes_intl_to_intl_aliyun():
    assert china_llm.api_base_for("qwen_ai_platform", "intl") == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )


def test_deepseek_has_no_region_endpoint():
    """DeepSeek only has one global endpoint — should return None, not invent one."""
    assert china_llm.api_base_for("deepseek", "intl") is None
    assert china_llm.api_base_for("deepseek", "cn") is None


# ---------------------------------------------------------------------------
# Env-var discovery
# ---------------------------------------------------------------------------
def test_discover_returns_none_when_nothing_set(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert china_llm.discover_api_key("deepseek") is None


def test_discover_finds_set_env_var(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    assert china_llm.discover_api_key("deepseek") == "sk-test-123"


def test_qwen_falls_back_to_dashscope_key(monkeypatch):
    """Qwen accepts both QWENCLOUD_API_KEY and DASHSCOPE_API_KEY."""
    monkeypatch.delenv("QWENCLOUD_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_AI_PLATFORM_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fallback-key")
    assert china_llm.discover_api_key("qwencloud") == "fallback-key"


def test_qwencloud_prefers_its_own_key_over_legacy(monkeypatch):
    """Priority order: QWENCLOUD > DASHSCOPE."""
    monkeypatch.setenv("QWENCLOUD_API_KEY", "primary")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fallback")
    assert china_llm.discover_api_key("qwencloud") == "primary"


def test_volcengine_accepts_ark_alias(monkeypatch):
    """Volcengine also reads ARK_API_KEY (the older env var)."""
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    assert china_llm.discover_api_key("volcengine") == "ark-key"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def test_resolve_with_explicit_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    resolved = china_llm.resolve("deepseek-v3", api_key="explicit-key")
    assert resolved == {
        "model": "deepseek/deepseek-chat",
        "api_key": "explicit-key",
    }


def test_resolve_picks_up_env_var(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    resolved = china_llm.resolve("deepseek-v3")
    assert resolved["api_key"] == "env-key"
    assert resolved["model"] == "deepseek/deepseek-chat"


def test_resolve_includes_api_base_for_region_routed_providers(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "k")
    resolved_cn = china_llm.resolve("kimi-v1-8k", region="cn")
    assert resolved_cn["api_base"] == "https://api.moonshot.cn/v1"
    resolved_intl = china_llm.resolve("kimi-v1-8k", region="intl")
    assert resolved_intl["api_base"] == "https://api.moonshot.ai/v1"


def test_resolve_omits_api_base_when_not_region_routed(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    resolved = china_llm.resolve("deepseek-v3")
    assert "api_base" not in resolved


def test_resolve_unknown_preset_raises():
    with pytest.raises(KeyError, match="Unknown preset"):
        china_llm.resolve("does-not-exist", api_key="x")


def test_resolve_missing_key_raises_configuration_error(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        china_llm.resolve("deepseek-v3")


# ---------------------------------------------------------------------------
# Helper functions (shortcut access)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "helper,preset_name",
    [
        (china_llm.deepseek_v3, "deepseek-v3"),
        (china_llm.qwen_max, "qwen-max"),
        (china_llm.glm_4_7, "glm-4.7"),
        (china_llm.glm_flash, "glm-flash"),
        (china_llm.kimi_v1_128k, "kimi-v1-128k"),
        (china_llm.doubao_flash, "doubao-flash"),
    ],
)
def test_helper_functions_return_preset(helper, preset_name):
    preset = helper()
    assert preset.name == preset_name


# ---------------------------------------------------------------------------
# Integration with ScrapeRequest (preset names as llm_model)
# ---------------------------------------------------------------------------
async def test_scrape_with_china_preset_resolves_to_litellm(monkeypatch, respx_mock):
    """End-to-end: passing 'deepseek-v3' as llm_model must reach litellm with
    the right model string AND the right api_key, even with no explicit key."""
    import httpx

    from scrapex import (
        ExtractionStrategy,
        FieldSpec,
        Schema,
        ScrapeRequest,
        scrape,
    )

    # Mock the HTTP fetch
    respx_mock.get(url__regex=r"^https://example\.com/?$").mock(
        return_value=httpx.Response(200, text="<html><body><p>hi</p></body></html>")
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek-key")

    # Capture what gets passed to litellm
    captured: dict = {}

    class FakeMessage:
        content = '{"title": "hi"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        from typing import ClassVar

        choices: ClassVar = [FakeChoice()]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    # Patch the LLM extractor's litellm instance. We need to set _litellm
    # to an object with our fake acompletion — _ensure_litellm() would
    # overwrite _litellm with the real litellm on first call, so we
    # monkeypatch the class method instead.
    from scrapex.extractors.llm import LlmExtractor

    monkeypatch.setattr(
        LlmExtractor,
        "_ensure_litellm",
        lambda self: setattr(
            self,
            "_litellm",
            type(
                "FakeLitellm",
                (),
                {
                    "acompletion": staticmethod(fake_acompletion),
                },
            )(),
        ),
    )

    await scrape(
        ScrapeRequest(
            url="https://example.com",
            schema=Schema(
                strategy=ExtractionStrategy.LLM,
                fields=[FieldSpec(name="title", description="page title")],
            ),
            llm_model="deepseek-v3",  # preset name, not raw litellm string
        )
    )

    assert captured["model"] == "deepseek/deepseek-chat"
    assert captured["api_key"] == "env-deepseek-key"
