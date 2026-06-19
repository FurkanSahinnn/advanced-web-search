"""
Local multilingual embeddings (BAAI/bge-m3 by default).

Default backend is fastembed (ONNX, CPU, no torch -> small install). Setting
`use_torch_models=True` switches to sentence-transformers. The model is loaded
lazily on first use and cached in the data dir. All calls are CPU-bound, so
async callers use the `aembed_*` wrappers (run in a thread).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

from ..config import get_settings

_model = None
_backend: Optional[str] = None
_lock = threading.Lock()


def _load():
    global _model, _backend
    if _model is not None:
        return _model, _backend
    with _lock:
        if _model is not None:
            return _model, _backend
        settings = get_settings()
        if settings.use_torch_models:
            try:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(
                    settings.embed_model, cache_folder=str(settings.model_cache_path)
                )
                _backend = "st"
                return _model, _backend
            except Exception:
                pass
        # fastembed (default)
        from fastembed import TextEmbedding

        _model = TextEmbedding(
            model_name=settings.embed_model, cache_dir=str(settings.model_cache_path)
        )
        _backend = "fastembed"
        return _model, _backend


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model, backend = _load()
    if backend == "st":
        arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, v)) for v in arr]
    # fastembed returns a generator of numpy arrays
    return [list(map(float, v)) for v in model.embed(texts)]


def embed_query(text: str) -> list[float]:
    out = embed_texts([text])
    return out[0] if out else []


async def aembed_texts(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(embed_texts, texts)


async def aembed_query(text: str) -> list[float]:
    return await asyncio.to_thread(embed_query, text)


def warm_up() -> bool:
    """Trigger model download/load ahead of first run. Returns True on success."""
    try:
        embed_texts(["advanced-web-search warm-up"])
        return True
    except Exception:
        return False
