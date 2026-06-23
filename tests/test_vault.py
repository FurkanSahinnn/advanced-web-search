"""
Offline tests for the encrypted API-key vault + LLM-routing overrides.

Exercises the REAL crypto (AES-GCM/PBKDF2 via `cryptography`) and the REAL
app_settings persistence against a fresh temp DB (the `fresh_env` fixture). No
network and no LLM calls — only key sealing/resolution and the pure routing
logic in `provider._prepare`.
"""

from __future__ import annotations

import pytest

from advanced_web_search.llm import provider, vault


@pytest.fixture(autouse=True)
def _clean_vault_state(monkeypatch):
    # The vault keeps process-global in-memory unlock state; reset it around
    # every test so cases don't leak a derived key into one another. Also clear
    # any REAL cloud key from the environment (the developer's .env may hold
    # one) so env-fallback assertions are deterministic.
    for env in vault.CLOUD_ENV.values():
        monkeypatch.delenv(env, raising=False)
    vault.lock()
    vault._unlock_failures = 0  # reset the cross-test brute-force back-off counter
    yield
    vault.lock()


def test_setup_unlock_lock_roundtrip(fresh_env):
    assert vault.is_configured() is False
    assert vault.is_unlocked() is False

    assert vault.setup("hunter2-strong")["ok"] is True
    assert vault.is_configured() is True
    assert vault.is_unlocked() is True  # setup auto-unlocks

    # A second setup must refuse (already configured).
    assert vault.setup("other")["ok"] is False

    # Store a cloud key and read it back through the effective resolver.
    assert vault.set_key("openai", "sk-test-ABCD1234")["ok"] is True
    assert vault.effective_cloud_key("openai") == "sk-test-ABCD1234"
    assert "openai" in vault.available_cloud_providers()
    assert vault.cloud_providers_with_keys() == ["openai"]

    ks = vault.key_status("openai")
    assert ks == {"key_set": True, "key_source": "vault", "key_hint": "1234"}

    # Locking drops the in-memory key: the value is unreadable, the env is empty,
    # but the provider NAME is still known (so the UI can show "stored, locked").
    vault.lock()
    assert vault.is_unlocked() is False
    assert vault.effective_cloud_key("openai") is None
    assert vault.available_cloud_providers() == []
    assert vault.cloud_providers_with_keys() == ["openai"]
    assert vault.key_status("openai")["key_hint"] is None  # no plaintext while locked

    # Wrong password keeps it locked; the right one restores the key.
    assert vault.unlock("nope")["ok"] is False
    assert vault.is_unlocked() is False
    assert vault.unlock("hunter2-strong")["ok"] is True
    assert vault.effective_cloud_key("openai") == "sk-test-ABCD1234"


def test_change_password_and_reset(fresh_env):
    vault.setup("old-pass-12")
    vault.set_key("anthropic", "sk-ant-XYZ9")

    # Re-key: old password verifies, secrets survive, old password stops working.
    assert vault.change_password("wrong", "new-pass-12")["ok"] is False
    assert vault.change_password("old-pass-12", "new-pass-12")["ok"] is True
    vault.lock()
    assert vault.unlock("old-pass-12")["ok"] is False
    assert vault.unlock("new-pass-12")["ok"] is True
    assert vault.effective_cloud_key("anthropic") == "sk-ant-XYZ9"

    # Delete a single key.
    assert vault.delete_key("anthropic")["ok"] is True
    assert vault.effective_cloud_key("anthropic") is None
    assert vault.cloud_providers_with_keys() == []

    # Reset wipes the whole vault.
    vault.set_key("openai", "sk-2")
    vault.reset()
    assert vault.is_configured() is False
    assert vault.is_unlocked() is False
    assert vault.cloud_providers_with_keys() == []


def test_env_fallback_when_locked_or_unconfigured(fresh_env, monkeypatch):
    # With no vault and a key in the environment, the env key is used (legacy).
    monkeypatch.setenv("GROQ_API_KEY", "gsk-env-7777")
    assert vault.effective_cloud_key("groq") == "gsk-env-7777"
    assert "groq" in vault.available_cloud_providers()
    assert vault.key_status("groq") == {
        "key_set": True,
        "key_source": "env",
        "key_hint": "7777",
    }


def test_setup_rejects_short_password(fresh_env):
    res = vault.setup("short")  # 5 chars < minimum
    assert res["ok"] is False
    assert vault.is_configured() is False
    # A sufficiently long password is accepted.
    assert vault.setup("long-enough-1")["ok"] is True


def test_set_key_requires_unlocked(fresh_env):
    vault.setup("pw-123456")
    vault.lock()
    res = vault.set_key("openai", "sk-x")
    assert res["ok"] is False
    assert res["error"] == "vault locked"


def test_runtime_overrides(fresh_env):
    # active_llm
    assert vault.current_active_llm() == {"kind": "auto", "provider": None}
    vault.set_active_llm("cloud", "openai")
    assert vault.current_active_llm() == {"kind": "cloud", "provider": "openai"}

    # ollama base url + local model overrides
    vault.set_ollama_base_url("http://box:11434")
    assert vault.current_ollama_base_url() == "http://box:11434"
    vault.set_local_model("qwen3:14b")
    assert vault.current_local_model() == "qwen3:14b"

    # custom OpenAI-compatible endpoint
    vault.set_custom_endpoint("http://localhost:1234/v1", "my-model")
    ce = vault.current_custom_endpoint()
    assert ce == {"base_url": "http://localhost:1234/v1", "model": "my-model"}


def test_prepare_routes_each_backend(fresh_env, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    vault.setup("pw-123456")

    # Ollama -> (DB-overridable) api_base, model id unchanged.
    vault.set_ollama_base_url("http://box:11434")
    model, kw = provider._prepare("ollama_chat/qwen3:8b")
    assert model == "ollama_chat/qwen3:8b"
    assert kw == {"api_base": "http://box:11434"}

    # Custom -> openai/<model> + endpoint base_url + endpoint key (or sk-noauth).
    vault.set_custom_endpoint("http://localhost:1234/v1", "local-model")
    vault.set_key("custom", "ep-secret")
    model, kw = provider._prepare("custom/local-model")
    assert model == "openai/local-model"
    assert kw == {"api_base": "http://localhost:1234/v1", "api_key": "ep-secret"}

    # Cloud -> explicit api_key injected from the vault.
    vault.set_key("openai", "sk-cloud-key")
    model, kw = provider._prepare("openai/gpt-4o-mini")
    assert model == "openai/gpt-4o-mini"
    assert kw == {"api_key": "sk-cloud-key"}

    # Unknown/local-only cloud prefix with no key -> no kwargs (litellm env path).
    model, kw = provider._prepare("gemini/gemini-2.5-flash")
    assert model == "gemini/gemini-2.5-flash"
    assert kw == {}


def test_default_model_follows_active_selection(fresh_env, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    vault.setup("pw-123456")

    # Pinned cloud provider (with a stored key) wins.
    vault.set_key("openai", "sk-k")
    vault.set_active_llm("cloud", "openai")
    assert provider._default_model() == "openai/gpt-4o-mini"

    # Pinned custom endpoint -> the custom/<model> sentinel.
    vault.set_custom_endpoint("http://localhost:1234/v1", "local-model")
    vault.set_active_llm("custom", None)
    assert provider._default_model() == "custom/local-model"

    # Pinned ollama -> a local ollama_chat id.
    vault.set_active_llm("ollama", None)
    assert provider._default_model().startswith("ollama_chat/")
