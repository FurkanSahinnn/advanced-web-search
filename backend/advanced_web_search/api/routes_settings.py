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
from ..llm.hardware import hardware_info
from ..llm.provider import effective_model_map, llm_status
from ..models.schemas import (
    LLMStatus,
    ModelMap,
    ProviderStatus,
    ScoreWeights,
    SettingsOut,
    SettingsUpdate,
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
    settings = get_settings()
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

    # Cloud LLM providers.
    available_cloud = set(settings.available_cloud_providers)
    for name in CLOUD_DEFAULTS:
        out.append(
            ProviderStatus(
                name=name,
                kind="cloud",
                available=name in available_cloud,
                requires_key=True,
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
    providers = _build_providers(llm)

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

    return await _settings_payload()
