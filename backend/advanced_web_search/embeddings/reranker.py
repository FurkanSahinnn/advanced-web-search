"""
Cross-encoder reranker (fastembed ONNX backend, CPU, no torch).

A lazy singleton model is loaded on first use with a fallback chain of model
ids. If every candidate model fails to load, the reranker degrades to an
"identity" mode that preserves the input order (callers still get one score
per doc). Nothing here ever raises to the caller: on any failure we log and
degrade.

All work is CPU-bound, so async callers use `arerank` (runs in a thread).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from ..config import get_settings

log = logging.getLogger("advanced_web_search.reranker")

# Fallback chain tried after the configured model. fastembed-supported,
# multilingual-first then smaller English models.
_FALLBACK_MODELS: list[str] = [
    "jinaai/jina-reranker-v2-base-multilingual",
    "BAAI/bge-reranker-base",
    "Xenova/ms-marco-MiniLM-L-6-v2",
]

_model = None
_mode: Optional[str] = None          # "cross_encoder" | "identity" | None (unloaded)
_model_id: Optional[str] = None
_lock = threading.Lock()


def _candidate_models() -> list[str]:
    """Configured model first, then the fallback chain (deduped, order kept)."""
    try:
        configured = get_settings().rerank_model
    except Exception:
        configured = None
    ordered: list[str] = []
    for m in [configured, *_FALLBACK_MODELS]:
        if m and m not in ordered:
            ordered.append(m)
    return ordered


def _load():
    """Lazy singleton load with a fallback chain. Sets identity mode on total failure."""
    global _model, _mode, _model_id
    if _mode is not None:
        return _model, _mode
    with _lock:
        if _mode is not None:
            return _model, _mode

        cache_dir = None
        try:
            cache_dir = str(get_settings().model_cache_path)
        except Exception:
            cache_dir = None

        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except Exception as exc:
            log.warning("fastembed TextCrossEncoder unavailable: %s", exc)
            _model, _mode, _model_id = None, "identity", None
            return _model, _mode

        for model_id in _candidate_models():
            try:
                if cache_dir:
                    _model = TextCrossEncoder(model_name=model_id, cache_dir=cache_dir)
                else:
                    _model = TextCrossEncoder(model_name=model_id)
                _mode = "cross_encoder"
                _model_id = model_id
                log.info("reranker loaded: %s", model_id)
                return _model, _mode
            except Exception as exc:
                log.warning("reranker model failed to load (%s): %s", model_id, exc)
                _model = None

        log.warning("no reranker model could be loaded; using identity mode")
        _model, _mode, _model_id = None, "identity", None
        return _model, _mode


def rerank(query: str, docs: list[str]) -> list[float]:
    """Return one raw relevance score per doc (higher = better).

    In identity mode returns strictly descending scores [1.0, 0.99, ...] so the
    caller's original ordering is preserved after any sort. Never raises.
    """
    if not docs:
        return []

    try:
        model, mode = _load()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("reranker load raised: %s", exc)
        model, mode = None, "identity"

    if mode == "cross_encoder" and model is not None:
        try:
            scores = list(model.rerank(query or "", list(docs)))
            if len(scores) == len(docs):
                return [float(s) for s in scores]
            log.warning(
                "reranker returned %d scores for %d docs; falling back to identity",
                len(scores), len(docs),
            )
        except Exception as exc:
            log.warning("reranker.rerank failed, degrading to identity: %s", exc)

    # identity / degraded: descending scores preserve original order
    n = len(docs)
    return [max(0.0, 1.0 - 0.01 * i) for i in range(n)]


async def arerank(query: str, docs: list[str]) -> list[float]:
    """Async wrapper around `rerank` (runs the CPU-bound model in a thread)."""
    try:
        return await asyncio.to_thread(rerank, query, docs)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("arerank failed: %s", exc)
        n = len(docs)
        return [max(0.0, 1.0 - 0.01 * i) for i in range(n)]


def warm_up() -> bool:
    """Trigger model download/load ahead of first run. Returns True if a real
    cross-encoder is available (identity mode counts as a non-fatal False)."""
    try:
        _model_obj, mode = _load()
        if mode != "cross_encoder":
            return False
        # exercise the path once so weights are fully materialized
        rerank("warm up", ["advanced-web-search reranker warm-up document"])
        return True
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("reranker warm_up failed: %s", exc)
        return False
