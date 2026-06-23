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

import contextvars
import json
import re
from typing import Any, AsyncIterator, Optional

from ..config import AGENT_ROLES, CLOUD_DEFAULTS, get_settings
from ..models.schemas import LLMStatus, ModelMap
from . import vault
from .hardware import recommend_local_model


# --------------------------------------------------------------------------- #
# Per-run LLM cost / token accounting
# --------------------------------------------------------------------------- #
# `run_stream` installs a fresh accumulator before driving the graph; every
# completion folds its token usage + $ estimate into it BY REFERENCE. Because
# child tasks (the researcher/verifier fan-outs, every LangGraph node) copy this
# context at creation, they all mutate the same dict — so the totals are complete
# without threading run_id through every chat() call or changing any node
# signature. Outside a tracked run (e.g. a Settings "Verify" probe) the var is
# None and recording is a silent no-op. Best-effort throughout: usage/cost are
# informational, so a provider that omits usage simply contributes 0.
_COST_CTX: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "aws_llm_cost", default=None
)


def begin_cost_capture() -> dict:
    """Install + return a fresh per-run usage accumulator (caller keeps the ref)."""
    acc: dict = {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "cost_usd": 0.0, "calls": 0, "by_role": {},
    }
    _COST_CTX.set(acc)
    return acc


def current_cost() -> Optional[dict]:
    """The active per-run usage accumulator, or None outside a tracked run."""
    return _COST_CTX.get()


def reset_cost_capture() -> None:
    """Detach the accumulator so out-of-run completions don't record into it."""
    _COST_CTX.set(None)


def _record_usage(resp: Any, role: str) -> None:
    """Best-effort: fold one completion's token usage + $ estimate into the run."""
    acc = _COST_CTX.get()
    if acc is None or resp is None:
        return
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        tt = int(getattr(usage, "total_tokens", 0) or 0) or (pt + ct)
    except Exception:
        return
    cost = 0.0
    try:
        import litellm

        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            cost = 0.0
        if cost <= 0.0 and (pt or ct):
            model = getattr(resp, "model", None) or ""
            if model:
                cost = _cost_per_token(model, pt, ct)
    except Exception:
        cost = 0.0
    _accumulate(role, pt, ct, tt, cost)


def _cost_per_token(model: str, pt: int, ct: int) -> float:
    """Best-effort $ from token counts via litellm (0.0 on any failure)."""
    try:
        import litellm

        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=pt, completion_tokens=ct
        )
        return float(prompt_cost or 0.0) + float(completion_cost or 0.0)
    except Exception:
        return 0.0


def _accumulate(role: str, pt: int, ct: int, tt: int, cost: float) -> None:
    """Fold one completion's tokens + cost into the active accumulator."""
    acc = _COST_CTX.get()
    if acc is None:
        return
    try:
        acc["prompt_tokens"] += pt
        acc["completion_tokens"] += ct
        acc["total_tokens"] += tt
        acc["cost_usd"] += cost
        acc["calls"] += 1
        br = acc["by_role"].setdefault(role, {"tokens": 0, "cost_usd": 0.0, "calls": 0})
        br["tokens"] += tt
        br["cost_usd"] += cost
        br["calls"] += 1
    except Exception:
        pass


def _record_stream_estimate(model: str, messages: list[dict], output_text: str, role: str) -> None:
    """Fallback usage for a stream whose provider sent no usage chunk.

    The streamed report is the single biggest token sink, so when no usage chunk
    arrives (some backends / the custom route, where `include_usage` is skipped)
    we estimate tokens from the prompt + streamed output via litellm's tokenizer
    so it isn't silently counted as 0. Fully best-effort; never raises.
    """
    if _COST_CTX.get() is None or not output_text:
        return
    try:
        import litellm

        real_model, _extra = _prepare(model)
        try:
            pt = int(litellm.token_counter(model=real_model, messages=messages) or 0)
        except Exception:
            pt = 0
        try:
            ct = int(litellm.token_counter(model=real_model, text=output_text) or 0)
        except Exception:
            ct = 0
        if not (pt or ct):
            return
        _accumulate(role, pt, ct, pt + ct, _cost_per_token(real_model, pt, ct))
    except Exception:
        return


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


def escalate(role: str) -> str:
    """A STRONGER model id for ``role`` (for re-checking a contested claim).

    The result is a raw litellm model id that callers pass straight into
    ``chat``/``chat_json`` (``resolve`` is pass-through for raw ids), so no node
    signature changes. Escalation is RAM-clamped for local models (only goes up a
    tier that actually fits) and only swaps a cloud model when its key is present.
    Returns the CURRENT model id unchanged when no stronger option exists (top
    local tier / provider with no strong sibling) so callers can cheaply detect a
    no-op. Never raises.
    """
    try:
        current = resolve(role)
    except Exception:
        return role
    try:
        if _is_ollama(current):
            from .hardware import next_local_tier

            name = current.rsplit("/", 1)[-1]
            stronger = next_local_tier(name, ram_clamped=True)
            return current if stronger == name else f"ollama_chat/{stronger}"
        prov = _provider_of(current)
        if prov:
            from ..config import CLOUD_STRONG

            strong = CLOUD_STRONG.get(prov)
            if strong and strong != current and vault.effective_cloud_key(prov):
                return strong
        return current
    except Exception:
        return current


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
        _record_usage(resp, role)
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
                _record_usage(resp, role)  # the fallback is a 2nd billable call
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
    # include_usage asks the provider for a final usage-bearing chunk. Safe for
    # cloud (honored) and ollama (litellm ignores/drops it), but a raw self-hosted
    # OpenAI-compatible server may 400 on it — which would silently demote the live
    # stream to the buffered chat() fallback. Skip it for the custom route; that
    # path still gets usage from the token-count estimate below.
    if not model.startswith("custom/"):
        kw["stream_options"] = {"include_usage": True}
    if max_tokens:
        kw["max_tokens"] = max_tokens
    try:
        stream = await _acompletion(model, messages, **kw)
        saw_usage = False
        out_parts: list[str] = []
        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                _record_usage(chunk, role)  # final usage chunk (empty choices)
                saw_usage = True
            try:
                tok = chunk.choices[0].delta.content
            except Exception:
                tok = None
            if tok:
                out_parts.append(tok)
                yield tok
        # No usage chunk arrived (custom route / a provider that omits it):
        # estimate from the prompt + streamed output so the report isn't 0.
        if not saw_usage and out_parts:
            _record_stream_estimate(model, messages, "".join(out_parts), role)
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
