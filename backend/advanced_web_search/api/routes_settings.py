"""Settings + provider/hardware/LLM status endpoints."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import CLOUD_DEFAULTS, DEFAULT_SCORE_WEIGHTS, DEPTH_PRESETS, get_settings
from ..db import repositories
from ..llm import provider as llm_provider
from ..llm import vault
from ..llm.hardware import hardware_info
from ..llm.provider import effective_model_map, llm_status
from ..models.schemas import (
    ActiveLLM,
    CustomEndpoint,
    LLMStatus,
    ModelMap,
    ProviderStatus,
    ScoreWeights,
    SettingsOut,
    SettingsUpdate,
    VaultStatus,
)
from ..sources.registry import all_providers

router = APIRouter(tags=["settings"])


class TestLLMBody(BaseModel):
    role: Optional[str] = None
    model: Optional[str] = None  # test THIS exact model id (e.g. the unsaved draft)


@router.post("/settings/test-llm")
async def test_llm_endpoint(body: Optional[TestLLMBody] = None) -> dict:
    """Run a tiny completion to confirm the configured LLM actually responds.

    If ``model`` is given, that exact model id is tested directly (so the UI can
    test an UNSAVED draft model the user just typed); otherwise the saved/effective
    model for ``role`` is tested. Never raises: any failure (no provider configured,
    bad model id, timeout, network) is reported as ``ok: false`` + an error message.
    """
    role = (body.role if body else None) or "planner"
    model_override = (body.model if body else None) or None
    model_override = model_override.strip() if model_override else None
    target = model_override or role  # provider.chat() passes a raw model id through unchanged

    # Resolve the active provider + concrete model for reporting.
    active_provider = None
    resolved_model = None
    try:
        status = await llm_status()
        active_provider = status.active_provider
    except Exception:
        active_provider = None
    try:
        resolved_model = model_override or effective_model_map().get(role)
    except Exception:
        resolved_model = model_override

    started = time.monotonic()
    text = ""
    error: Optional[str] = None
    try:
        text = await asyncio.wait_for(
            llm_provider.chat(
                target,
                [{"role": "user", "content": "Reply with the single word OK."}],
                max_tokens=5,
            ),
            timeout=25,
        )
    except asyncio.TimeoutError:
        error = "timeout: the model did not respond within 25s"
    except Exception as exc:  # never raise out of this endpoint
        error = str(exc) or exc.__class__.__name__

    latency_ms = int((time.monotonic() - started) * 1000)
    sample = (text or "").strip()
    ok = bool(sample)
    if not ok and error is None:
        error = "empty response (no model configured or model returned nothing)"

    return {
        "ok": ok,
        "provider": active_provider,
        "model": resolved_model,
        "latency_ms": latency_ms,
        "sample": sample[:40],
        "error": error,
    }


def _build_providers(llm: LLMStatus) -> list[ProviderStatus]:
    """Compose the provider-status list (sources + cloud LLM providers + ollama)."""
    out: list[ProviderStatus] = []

    # Source providers (web / academic).
    for p in all_providers():
        try:
            available = bool(p.enabled())
        except Exception:
            available = False
        out.append(
            ProviderStatus(
                name=p.name,
                kind=p.kind,  # "web" | "academic"
                available=available,
                requires_key=bool(getattr(p, "requires_key", False)),
            )
        )

    # Cloud LLM providers — availability + (non-secret) key status from the vault.
    available_cloud = set(vault.available_cloud_providers())
    for name in CLOUD_DEFAULTS:
        ks = vault.key_status(name)
        out.append(
            ProviderStatus(
                name=name,
                kind="cloud",
                available=name in available_cloud,
                requires_key=True,
                key_set=ks["key_set"],
                key_source=ks["key_source"],
                key_hint=ks["key_hint"],
            )
        )

    # Local Ollama.
    out.append(
        ProviderStatus(
            name="ollama",
            kind="local",
            available=bool(llm.ollama_available),
            requires_key=False,
            note="Install from https://ollama.com for offline LLM." if not llm.ollama_available else None,
        )
    )
    return out


def _runtime_cfg() -> dict:
    """Read all vault + LLM-routing overrides in one worker thread (DB reads)."""
    return {
        "vault": {
            "configured": vault.is_configured(),
            "unlocked": vault.is_unlocked(),
            "providers": vault.cloud_providers_with_keys(),
        },
        "active_llm": vault.current_active_llm(),
        "custom_endpoint": vault.current_custom_endpoint(),
        "custom_key_set": vault.has_custom_key(),
        "ollama_base_url": vault.current_ollama_base_url(),
        "local_model": vault.current_local_model(),
    }


async def _settings_payload() -> SettingsOut:
    settings = get_settings()

    (
        stored_model_map,
        stored_weights,
        stored_require_approval,
        stored_use_local_llm,
        stored_keep_threshold,
        stored_max_subtopics,
        stored_results_per_source,
        stored_depth,
        stored_max_research_rounds,
        stored_gap_min_sources,
        stored_query_variants,
        stored_snowball_top_k,
    ) = await asyncio.gather(
        asyncio.to_thread(repositories.get_setting, "model_map"),
        asyncio.to_thread(repositories.get_setting, "weights"),
        asyncio.to_thread(repositories.get_setting, "require_approval"),
        asyncio.to_thread(repositories.get_setting, "use_local_llm"),
        asyncio.to_thread(repositories.get_setting, "keep_threshold"),
        asyncio.to_thread(repositories.get_setting, "max_subtopics"),
        asyncio.to_thread(repositories.get_setting, "results_per_source"),
        asyncio.to_thread(repositories.get_setting, "depth"),
        asyncio.to_thread(repositories.get_setting, "max_research_rounds"),
        asyncio.to_thread(repositories.get_setting, "gap_min_sources"),
        asyncio.to_thread(repositories.get_setting, "query_variants"),
        asyncio.to_thread(repositories.get_setting, "snowball_top_k"),
    )

    # model_map: effective defaults overlaid with persisted per-role overrides.
    merged_map = dict(effective_model_map())
    if stored_model_map:
        merged_map.update({k: v for k, v in stored_model_map.items() if v})
    model_map = ModelMap(**{k: v for k, v in merged_map.items() if k in ModelMap.model_fields})

    weights = ScoreWeights(**(stored_weights or DEFAULT_SCORE_WEIGHTS))

    require_approval = (
        settings.require_approval if stored_require_approval is None else bool(stored_require_approval)
    )
    use_local_llm = (
        settings.use_local_llm if stored_use_local_llm is None else bool(stored_use_local_llm)
    )
    keep_threshold = (
        settings.keep_threshold if stored_keep_threshold is None else float(stored_keep_threshold)
    )
    max_subtopics = int(stored_max_subtopics) if stored_max_subtopics else settings.max_subtopics
    results_per_source = (
        int(stored_results_per_source) if stored_results_per_source else settings.results_per_source
    )

    depth = stored_depth or settings.depth
    max_research_rounds = (
        int(stored_max_research_rounds) if stored_max_research_rounds is not None
        else settings.max_research_rounds
    )
    gap_min_sources = (
        int(stored_gap_min_sources) if stored_gap_min_sources is not None
        else settings.gap_min_sources
    )
    query_variants = (
        int(stored_query_variants) if stored_query_variants is not None
        else settings.query_variants
    )
    snowball_top_k = (
        int(stored_snowball_top_k) if stored_snowball_top_k is not None
        else settings.snowball_top_k
    )

    hw = await asyncio.to_thread(hardware_info)
    llm = await llm_status()
    # _build_providers does synchronous DB-backed vault reads (key_status); keep
    # them off the event loop like the rest of the payload assembly.
    providers = await asyncio.to_thread(_build_providers, llm)
    cfg = await asyncio.to_thread(_runtime_cfg)

    ce = cfg["custom_endpoint"]
    return SettingsOut(
        model_map=model_map,
        weights=weights,
        require_approval=require_approval,
        use_local_llm=use_local_llm,
        keep_threshold=keep_threshold,
        max_subtopics=max_subtopics,
        results_per_source=results_per_source,
        depth=depth,
        max_research_rounds=max_research_rounds,
        gap_min_sources=gap_min_sources,
        query_variants=query_variants,
        snowball_top_k=snowball_top_k,
        depth_presets=dict(DEPTH_PRESETS),
        hardware=hw,
        llm=llm,
        providers=providers,
        vault=VaultStatus(**cfg["vault"]),
        active_llm=ActiveLLM(
            kind=cfg["active_llm"].get("kind", "auto"),
            provider=cfg["active_llm"].get("provider"),
        ),
        custom_endpoint=CustomEndpoint(
            base_url=ce.get("base_url") or None,
            model=ce.get("model") or None,
            key_set=cfg["custom_key_set"],
        ),
        ollama_base_url=cfg["ollama_base_url"],
        local_model=cfg["local_model"],
        cloud_defaults=dict(CLOUD_DEFAULTS),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings_endpoint() -> SettingsOut:
    return await _settings_payload()


@router.patch("/settings", response_model=SettingsOut)
async def update_settings_endpoint(body: SettingsUpdate) -> SettingsOut:
    async def _set(key: str, value) -> None:
        await asyncio.to_thread(repositories.set_setting, key, value)

    if body.model_map is not None:
        await _set("model_map", body.model_map.model_dump(exclude_none=True))
    if body.weights is not None:
        await _set("weights", body.weights.model_dump())
    if body.require_approval is not None:
        await _set("require_approval", bool(body.require_approval))
    if body.use_local_llm is not None:
        await _set("use_local_llm", bool(body.use_local_llm))
    if body.keep_threshold is not None:
        await _set("keep_threshold", float(body.keep_threshold))
    if body.max_subtopics is not None:
        await _set("max_subtopics", int(body.max_subtopics))
    if body.results_per_source is not None:
        await _set("results_per_source", int(body.results_per_source))
    if body.depth is not None:
        await _set("depth", str(body.depth))
    if body.max_research_rounds is not None:
        await _set("max_research_rounds", int(body.max_research_rounds))
    if body.gap_min_sources is not None:
        await _set("gap_min_sources", int(body.gap_min_sources))
    if body.query_variants is not None:
        await _set("query_variants", int(body.query_variants))
    if body.snowball_top_k is not None:
        await _set("snowball_top_k", int(body.snowball_top_k))

    # LLM provider/endpoint config (non-secret). API keys never travel here —
    # they go through the dedicated /settings/provider-key vault route.
    if body.active_llm is not None:
        await asyncio.to_thread(
            vault.set_active_llm, body.active_llm.kind, body.active_llm.provider
        )
    if body.ollama_base_url is not None:
        await asyncio.to_thread(vault.set_ollama_base_url, body.ollama_base_url)
    if body.local_model is not None:
        await asyncio.to_thread(vault.set_local_model, body.local_model)
    if body.custom_base_url is not None or body.custom_model is not None:
        cur = await asyncio.to_thread(vault.current_custom_endpoint)
        await asyncio.to_thread(
            vault.set_custom_endpoint,
            body.custom_base_url if body.custom_base_url is not None else cur.get("base_url"),
            body.custom_model if body.custom_model is not None else cur.get("model"),
        )

    return await _settings_payload()


# --------------------------------------------------------------------------- #
# Encrypted API-key vault + per-provider key management + live validation
# --------------------------------------------------------------------------- #

class VaultSetupBody(BaseModel):
    master_password: str


class VaultUnlockBody(BaseModel):
    master_password: str


class VaultChangeBody(BaseModel):
    old_password: str
    new_password: str


class VaultResetBody(BaseModel):
    # An explicit confirmation is required so a blind cross-site POST (which
    # can't read our response but could still trigger the side effect) can't
    # silently wipe the vault. The forgot-password flow stays password-free.
    confirm: bool = False


# Only these names may be used as vault secret keys (cloud providers + custom).
_ALLOWED_KEY_NAMES = set(vault.CLOUD_ENV) | {"custom"}


class ProviderKeyBody(BaseModel):
    provider: str          # cloud name (anthropic…openrouter) or "custom"
    key: str
    verify: bool = True     # live-validate cloud keys before storing


class ValidateKeyBody(BaseModel):
    provider: str
    key: str


class TestEndpointBody(BaseModel):
    base_url: str
    model: str
    api_key: Optional[str] = None


@router.get("/settings/vault")
async def vault_status_endpoint() -> dict:
    return (await asyncio.to_thread(_runtime_cfg))["vault"]


@router.post("/settings/vault/setup")
async def vault_setup_endpoint(body: VaultSetupBody) -> dict:
    """Set the master password the first time (auto-unlocks on success)."""
    return await asyncio.to_thread(vault.setup, body.master_password)


@router.post("/settings/vault/unlock")
async def vault_unlock_endpoint(body: VaultUnlockBody) -> dict:
    return await asyncio.to_thread(vault.unlock, body.master_password)


@router.post("/settings/vault/lock")
async def vault_lock_endpoint() -> dict:
    await asyncio.to_thread(vault.lock)
    return {"ok": True}


@router.post("/settings/vault/change-password")
async def vault_change_endpoint(body: VaultChangeBody) -> dict:
    return await asyncio.to_thread(vault.change_password, body.old_password, body.new_password)


@router.post("/settings/vault/reset")
async def vault_reset_endpoint(body: VaultResetBody) -> dict:
    """Forgot-password escape hatch: wipe the vault and all stored keys."""
    if not body.confirm:
        return {"ok": False, "error": "confirmation required"}
    await asyncio.to_thread(vault.reset)
    return {"ok": True}


@router.put("/settings/provider-key")
async def set_provider_key_endpoint(body: ProviderKeyBody) -> dict:
    """Validate (optionally) then encrypt-and-store a provider/custom key.

    Requires an unlocked vault. For cloud providers, a failed live validation
    aborts the store so a known-bad key is never persisted.
    """
    provider = (body.provider or "").strip()
    key = (body.key or "").strip()
    if provider not in _ALLOWED_KEY_NAMES:
        return {"ok": False, "stored": False, "validation": None, "error": "unknown provider"}
    validation = None
    if body.verify and provider != "custom":
        validation = await llm_provider.validate_key(provider, key)
        if not validation.get("ok"):
            return {
                "ok": False,
                "stored": False,
                "validation": validation,
                "error": validation.get("error"),
            }
    res = await asyncio.to_thread(vault.set_key, provider, key)
    return {
        "ok": bool(res.get("ok")),
        "stored": bool(res.get("ok")),
        "validation": validation,
        "error": res.get("error"),
    }


@router.delete("/settings/provider-key/{provider}")
async def delete_provider_key_endpoint(provider: str) -> dict:
    if provider not in _ALLOWED_KEY_NAMES:
        return {"ok": False, "error": "unknown provider"}
    return await asyncio.to_thread(vault.delete_key, provider)


@router.post("/settings/validate-key")
async def validate_key_endpoint(body: ValidateKeyBody) -> dict:
    """Live-test a candidate cloud key WITHOUT storing it (the Verify button)."""
    return await llm_provider.validate_key((body.provider or "").strip(), (body.key or "").strip())


@router.post("/settings/test-endpoint")
async def test_endpoint_endpoint(body: TestEndpointBody) -> dict:
    """Live-test a self-hosted OpenAI-compatible endpoint WITHOUT storing it."""
    return await llm_provider.test_endpoint(body.base_url, body.model, body.api_key)
