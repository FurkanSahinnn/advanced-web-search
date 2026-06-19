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
    settings = get_settings()
    name = settings.local_model or recommend_local_model()
    return f"ollama_chat/{name}"


def _default_model() -> str:
    settings = get_settings()
    providers = settings.available_cloud_providers
    if providers:
        return CLOUD_DEFAULTS[providers[0]]
    return _local_model_id()


def _persisted_overrides() -> dict[str, str]:
    """Read role->model overrides saved by the settings API (best-effort)."""
    try:
        from ..db.database import get_conn

        row = get_conn().execute(
            "SELECT value FROM app_settings WHERE key='model_map'"
        ).fetchone()
        if row:
            data = json.loads(row["value"])
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


def _call_kwargs(model: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if _is_ollama(model):
        kwargs["api_base"] = get_settings().ollama_base_url
    return kwargs


# --------------------------------------------------------------------------- #
# Completions
# --------------------------------------------------------------------------- #

async def _acompletion(model: str, messages: list[dict], **kw: Any):
    import litellm

    litellm.drop_params = True  # silently drop unsupported params per provider
    litellm.suppress_debug_info = True
    return await litellm.acompletion(model=model, messages=messages, **_call_kwargs(model), **kw)


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

    base = get_settings().ollama_base_url.rstrip("/")
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
    settings = get_settings()
    providers = settings.available_cloud_providers
    models = await ollama_models()
    emap = effective_model_map()
    if providers:
        mode = "cloud"
        active = providers[0]
    elif models:
        mode = "local"
        active = "ollama"
    else:
        mode = "none"
        active = None
    return LLMStatus(
        mode=mode,
        active_provider=active,
        effective_models=ModelMap(**emap),
        cloud_providers=providers,
        ollama_available=bool(models),
        ollama_models=models,
    )
