"""
Provider-agnostic LLM layer (LiteLLM).

Routing (the "hybrid" posture):
  * If a cloud API key is present -> use that provider's cheap+great default
    model for every agent role (Anthropic Claude Haiku 4.5 preferred).
  * Else -> use a local Ollama model sized to the machine.
Per-role overrides from persisted settings always win. A cloud call that
fails falls back once to the local model so a run never hard-stops.

Public surface used by graph nodes:
    effective_model_map() -> {role: model_id}
    await chat(role, messages, ...) -> str
    await chat_json(role, messages, ...) -> dict
    async for tok in chat_stream(role, messages, ...): ...
    await llm_status() -> LLMStatus
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Optional

from ..config import AGENT_ROLES, CLOUD_DEFAULTS, get_settings
from ..models.schemas import LLMStatus, ModelMap
from . import vault
from .hardware import recommend_local_model


# --------------------------------------------------------------------------- #
# Model resolution
# --------------------------------------------------------------------------- #

def local_llm_enabled() -> bool:
    """Whether the local Ollama LLM may be probed / used as a fallback.

    Reads the persisted ``use_local_llm`` toggle (set in Settings); if it has
    never been written, falls back to the process/env default
    (``AWSEARCH_USE_LOCAL_LLM``, defaulting to True). Defensive: any failure
    reading the DB falls back to the settings default rather than disabling.
    """
    try:
        from ..db import repositories  # lazy import (avoid import cycle / DB at import time)

        stored = repositories.get_setting("use_local_llm")
    except Exception:
        stored = None
    if stored is None:
        return bool(get_settings().use_local_llm)
    return bool(stored)


def _local_model_id() -> str:
    name = vault.current_local_model() or recommend_local_model()
    return f"ollama_chat/{name}"


def _custom_model_id() -> str | None:
    """The internal model id for a configured self-hosted endpoint, else None.

    Encoded as ``custom/<model>`` (NOT ``openai/<model>``) so ``_prepare`` can
    unambiguously route it to the user's ``api_base`` without colliding with a
    real OpenAI key. Returns None when the endpoint isn't fully configured.
    """
    ep = vault.current_custom_endpoint()
    if ep.get("base_url") and ep.get("model"):
        return f"custom/{ep['model']}"
    return None


def _default_model() -> str:
    """Pick the base model for every role from the user's active selection.

    ``active_llm.kind`` lets the UI pin cloud/ollama/custom explicitly; a
    misconfigured pin falls through to ``auto`` (cloud-if-key-else-local) so a
    run never hard-stops on a half-finished setting.
    """
    active = vault.current_active_llm()
    kind = active.get("kind", "auto")
    if kind == "ollama":
        return _local_model_id()
    if kind == "custom":
        custom = _custom_model_id()
        if custom:
            return custom
    if kind == "cloud":
        prov = active.get("provider")
        if prov and prov in CLOUD_DEFAULTS and vault.effective_cloud_key(prov):
            return CLOUD_DEFAULTS[prov]
    providers = vault.available_cloud_providers()
    if providers and providers[0] in CLOUD_DEFAULTS:
        return CLOUD_DEFAULTS[providers[0]]
    # Auto-fallback also honours a configured self-hosted endpoint before going
    # local, so this matches llm_status()'s mode ordering exactly.
    custom = _custom_model_id()
    if custom:
        return custom
    return _local_model_id()


def _persisted_overrides() -> dict[str, str]:
    """Read role->model overrides saved by the settings API (best-effort)."""
    try:
        from ..db import repositories

        data = repositories.get_setting("model_map")
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v}
    except Exception:
        pass
    return {}


def effective_model_map() -> dict[str, str]:
    base = _default_model()
    overrides = _persisted_overrides()
    return {role: overrides.get(role) or base for role in AGENT_ROLES}


def resolve(role_or_model: str) -> str:
    """Map an agent role to a concrete model id (pass-through if already a model id)."""
    if role_or_model in AGENT_ROLES:
        return effective_model_map()[role_or_model]
    return role_or_model


def _is_ollama(model: str) -> bool:
    return model.startswith("ollama")


def _provider_of(model: str) -> str | None:
    """The cloud provider name a litellm model id belongs to, else None."""
    head = model.split("/", 1)[0]
    return head if head in vault.CLOUD_ENV else None


def _prepare(model: str) -> tuple[str, dict[str, Any]]:
    """Resolve an internal model id to the real litellm id + per-call kwargs.

    Threads the right endpoint/credential WITHOUT mutating the process
    environment (so ``get_settings()``'s lru_cache and litellm's own env reads
    stay clean):
      * ``custom/<model>``  -> ``openai/<model>`` + self-hosted api_base/api_key
      * ``ollama*``         -> the (DB-overridable) Ollama api_base
      * cloud ids           -> explicit api_key from the vault when one is stored
        (else left to litellm's own environment-key resolution)
    """
    kwargs: dict[str, Any] = {}
    if model.startswith("custom/"):
        ep = vault.current_custom_endpoint()
        kwargs["api_base"] = ep.get("base_url") or ""
        kwargs["api_key"] = vault.effective_custom_key() or "sk-noauth"
        return "openai/" + model[len("custom/"):], kwargs
    if _is_ollama(model):
        kwargs["api_base"] = vault.current_ollama_base_url()
        return model, kwargs
    prov = _provider_of(model)
    if prov:
        key = vault.effective_cloud_key(prov)
        if key:
            kwargs["api_key"] = key
    return model, kwargs


# --------------------------------------------------------------------------- #
# Completions
# --------------------------------------------------------------------------- #

async def _acompletion(model: str, messages: list[dict], **kw: Any):
    import litellm

    litellm.drop_params = True  # silently drop unsupported params per provider
    litellm.suppress_debug_info = True
    real_model, extra = _prepare(model)
    return await litellm.acompletion(model=real_model, messages=messages, **extra, **kw)


async def chat(
    role: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
) -> str:
    model = resolve(role)
    kw: dict[str, Any] = {"temperature": temperature}
    if max_tokens:
        kw["max_tokens"] = max_tokens
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    try:
        resp = await _acompletion(model, messages, **kw)
        return resp.choices[0].message.content or ""
    except Exception:
        # One fallback to local if a cloud model failed — but ONLY when the user
        # allows local LLM. With it disabled we never silently hit a local model
        # the user opted out of; the cloud failure simply surfaces as "".
        if not local_llm_enabled():
            return ""
        local = _local_model_id()
        if model != local:
            try:
                resp = await _acompletion(local, messages, **kw)
                return resp.choices[0].message.content or ""
            except Exception:
                return ""
        return ""


async def chat_stream(
    role: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
) -> AsyncIterator[str]:
    model = resolve(role)
    kw: dict[str, Any] = {"temperature": temperature, "stream": True}
    if max_tokens:
        kw["max_tokens"] = max_tokens
    try:
        stream = await _acompletion(model, messages, **kw)
        async for chunk in stream:
            try:
                tok = chunk.choices[0].delta.content
            except Exception:
                tok = None
            if tok:
                yield tok
    except Exception:
        text = await chat(role, messages, temperature=temperature, max_tokens=max_tokens)
        if text:
            yield text


_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.S)


def _coerce_json(text: str) -> Any:
    text = text.strip()
    # strip ```json fences
    if text.startswith("```"):
        text = text.split("```", 2)[-1] if text.count("```") >= 2 else text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except Exception:
        m = _JSON_RE.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


async def chat_json(
    role: str,
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    retries: int = 2,
) -> Any:
    """Chat and parse a JSON object/array. Returns None if unparseable."""
    msgs = list(messages)
    for attempt in range(retries):
        text = await chat(role, msgs, temperature=temperature, max_tokens=max_tokens, json_mode=True)
        data = _coerce_json(text)
        if data is not None:
            return data
        msgs = messages + [{
            "role": "user",
            "content": "Return ONLY valid JSON. No prose, no code fences.",
        }]
    return None


# --------------------------------------------------------------------------- #
# Status / introspection
# --------------------------------------------------------------------------- #

_OLLAMA_PROBE: dict = {"t": -1e9, "models": []}
_OLLAMA_TTL = 10.0  # seconds; cache so back-to-back /settings loads don't re-probe


async def ollama_models() -> list[str]:
    """Fast, cached probe of the local Ollama server's models.

    Runs on EVERY GET /settings (and the no-model banner), so it must be quick:
    a SINGLE attempt with a short timeout (no retry/backoff), and the result —
    including a negative one — is cached for a few seconds so back-to-back
    settings loads are instant. When Ollama isn't running (cloud-only setups)
    we return [] fast instead of blocking the page.
    """
    import time

    from ..utils.http import get_client

    # When the user has disabled local LLM, do ZERO network work: no probe at
    # all (this is what removes the ~1s delay on the Settings page) and the
    # status layer then derives "cloud"/"none" with no local fallback.
    if not local_llm_enabled():
        return []

    now = time.monotonic()
    if now - _OLLAMA_PROBE["t"] < _OLLAMA_TTL:
        return list(_OLLAMA_PROBE["models"])

    base = vault.current_ollama_base_url().rstrip("/")
    models: list[str] = []
    try:
        client = await get_client()
        resp = await client.get(f"{base}/api/tags", timeout=0.8)
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("models") if isinstance(data, dict) else None
        models = [m.get("name", "") for m in (raw or []) if m.get("name")]
    except Exception:
        models = []
    _OLLAMA_PROBE["t"] = now
    _OLLAMA_PROBE["models"] = models
    return list(models)


async def llm_status() -> LLMStatus:
    providers = vault.available_cloud_providers()
    models = await ollama_models()
    emap = effective_model_map()
    active_cfg = vault.current_active_llm()
    kind = active_cfg.get("kind", "auto")
    custom = vault.current_custom_endpoint()
    custom_ready = bool(custom.get("base_url") and custom.get("model"))

    # Honour an explicit pin when it's actually usable, else fall through the
    # same auto order _default_model uses (cloud -> custom -> ollama -> none).
    mode = "none"
    active: str | None = None
    if kind == "custom" and custom_ready:
        mode, active = "custom", "custom"
    elif kind == "ollama" and models:
        mode, active = "local", "ollama"
    elif kind == "cloud" and active_cfg.get("provider") in providers:
        mode, active = "cloud", active_cfg.get("provider")
    elif providers:
        mode, active = "cloud", providers[0]
    elif custom_ready:
        mode, active = "custom", "custom"
    elif models:
        mode, active = "local", "ollama"

    return LLMStatus(
        mode=mode,
        active_provider=active,
        effective_models=ModelMap(**emap),
        cloud_providers=providers,
        ollama_available=bool(models),
        ollama_models=models,
    )


# --------------------------------------------------------------------------- #
# Credential / endpoint validation (the Settings "Verify" / "Test" buttons)
# --------------------------------------------------------------------------- #

# Provider SDK/litellm errors can echo the candidate key (e.g. "Incorrect API
# key provided: sk-..."). Scrub anything key-shaped before returning it to the UI.
_KEY_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{4,}|Bearer\s+\S{6,}|api[_-]?key['\"=:\s]+\S{6,})", re.I)


def _redact(msg: str) -> str:
    return _KEY_RE.sub("[REDACTED]", msg or "")


async def _probe(real_model: str, extra: dict[str, Any], *, timeout: float = 20.0) -> dict:
    """One tiny live completion; reports ok/latency/error without ever raising."""
    import asyncio
    import time

    import litellm

    litellm.drop_params = True
    litellm.suppress_debug_info = True
    started = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            litellm.acompletion(
                model=real_model,
                messages=[{"role": "user", "content": "Reply with the single word OK."}],
                max_tokens=5,
                **extra,
            ),
            timeout=timeout,
        )
        sample = (resp.choices[0].message.content or "").strip()
        latency = int((time.monotonic() - started) * 1000)
        if sample:
            return {"ok": True, "latency_ms": latency, "sample": sample[:40], "error": None}
        return {"ok": False, "latency_ms": latency, "sample": "", "error": "empty response"}
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "sample": "",
            "error": "timeout",
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "sample": "",
            "error": _redact(str(exc)) or exc.__class__.__name__,
        }


async def validate_key(provider: str, key: str) -> dict:
    """Make a tiny live call with a candidate cloud key (does NOT store it)."""
    model = CLOUD_DEFAULTS.get(provider)
    if not model:
        return {"ok": False, "latency_ms": 0, "sample": "", "error": f"unknown provider: {provider}"}
    if not key:
        return {"ok": False, "latency_ms": 0, "sample": "", "error": "empty key"}
    return await _probe(model, {"api_key": key})


async def test_endpoint(base_url: str, model: str, api_key: str | None = None) -> dict:
    """Live test of a self-hosted OpenAI-compatible endpoint (does NOT store)."""
    if not base_url or not model:
        return {"ok": False, "latency_ms": 0, "sample": "", "error": "base_url and model required"}
    extra = {"api_base": base_url, "api_key": api_key or "sk-noauth"}
    return await _probe("openai/" + model, extra)
