"""
Local multilingual embeddings (intfloat/multilingual-e5-large by default).

Default backend is fastembed (ONNX, CPU, no torch -> small install). Setting
`use_torch_models=True` switches to sentence-transformers. The model is loaded
lazily on first use and cached in the data dir. All calls are CPU-bound, so
async callers use the `aembed_*` wrappers (run in a thread).

Resilience: if the configured model can't be loaded (e.g. a fastembed version
dropped it — bge-m3 is no longer supported), we fall back to a known-supported
1024-dim multilingual model instead of disabling vector search entirely. e5
models are trained with "query:" / "passage:" prefixes, applied automatically.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from ..config import get_settings

log = logging.getLogger("advanced_web_search.embedder")

# Tried after the configured model. fastembed-supported, 1024-dim (to match the
# default ``embed_dim`` / vec0 table), multilingual first then an English 1024.
_FALLBACK_MODELS: list[str] = [
    "intfloat/multilingual-e5-large",
    "BAAI/bge-large-en-v1.5",
]

_model = None
_backend: Optional[str] = None
_model_id: Optional[str] = None
_lock = threading.Lock()


def _candidate_models() -> list[str]:
    """Configured model first, then the fallback chain (deduped, order kept)."""
    try:
        configured = get_settings().embed_model
    except Exception:
        configured = None
    ordered: list[str] = []
    for m in [configured, *_FALLBACK_MODELS]:
        if m and m not in ordered:
            ordered.append(m)
    return ordered


def _load():
    global _model, _backend, _model_id
    if _model is not None:
        return _model, _backend
    with _lock:
        if _model is not None:
            return _model, _backend
        settings = get_settings()
        cache_dir = str(settings.model_cache_path)

        # Optional sentence-transformers backend (opt-in). Falls through to
        # fastembed on any failure so a missing torch install is non-fatal.
        if settings.use_torch_models:
            try:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(settings.embed_model, cache_folder=cache_dir)
                _backend = "st"
                _model_id = settings.embed_model
                return _model, _backend
            except Exception as exc:
                log.warning("sentence-transformers load failed, trying fastembed: %s", exc)

        # fastembed (default), with a fallback chain.
        from fastembed import TextEmbedding

        for model_id in _candidate_models():
            try:
                _model = TextEmbedding(model_name=model_id, cache_dir=cache_dir)
                _backend = "fastembed"
                _model_id = model_id
                log.info("embedder loaded: %s", model_id)
                return _model, _backend
            except Exception as exc:
                log.warning("embed model failed to load (%s): %s", model_id, exc)
                _model = None

        # Nothing loaded — leave _model None so callers degrade to lexical-only.
        log.warning("no embedding model could be loaded; vector search disabled")
        return None, None


def _is_e5() -> bool:
    """e5 models need 'query:' / 'passage:' prefixes for good similarity."""
    return bool(_model_id and "e5" in _model_id.lower())


def _embed_raw(texts: list[str]) -> list[list[float]]:
    model, backend = _load()
    if model is None:
        return []
    if backend == "st":
        arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, v)) for v in arr]
    # fastembed returns a generator of numpy arrays
    return [list(map(float, v)) for v in model.embed(texts)]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed documents/passages."""
    if not texts:
        return []
    _load()  # resolve _model_id before deciding on prefixes
    if _is_e5():
        texts = [f"passage: {t}" for t in texts]
    return _embed_raw(texts)


def embed_query(text: str) -> list[float]:
    """Embed a search query (e5 uses a distinct 'query:' prefix)."""
    if not text:
        return []
    _load()
    payload = f"query: {text}" if _is_e5() else text
    out = _embed_raw([payload])
    return out[0] if out else []


async def aembed_texts(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(embed_texts, texts)


async def aembed_query(text: str) -> list[float]:
    return await asyncio.to_thread(embed_query, text)


def warm_up() -> bool:
    """Trigger model download/load ahead of first run. Returns True on success."""
    try:
        return bool(embed_texts(["advanced-web-search warm-up"]))
    except Exception:
        return False
