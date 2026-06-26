"""
Streaming helper for graph nodes.

Nodes call `emit(...)` to push a ResearchEvent-shaped frame to the UI.
Frames travel over LangGraph's custom stream channel; the API layer
(graph.astream(stream_mode="custom")) forwards them as SSE. If called
outside a streaming run context, emit() is a safe no-op.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models.schemas import EventType


def emit(
    type: EventType,
    run_id: int,
    *,
    node: Optional[str] = None,
    message: Optional[str] = None,
    **data: Any,
) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        writer = None
    if writer is None:
        return
    try:
        writer({
            "type": type,
            "run_id": run_id,
            "node": node,
            "message": message,
            "data": data,
        })
    except Exception:
        pass


def model_load_pending(kind: str) -> Optional[str]:
    """Return a user-facing 'loading model' notice if ``kind``'s model is not yet
    resident (peek only — never triggers a load), else ``None``.

    ``kind`` is ``"embed"`` or ``"rerank"``. The first use of either model lazily
    loads it and, on a fresh machine, downloads weights from HuggingFace (the
    embedder is ~2.3 GB) — a multi-minute step during which a research run
    otherwise looks frozen with no progress. Nodes call this right before the
    first embed/rerank to surface a ``log`` frame explaining the wait. Fully
    defensive: any failure returns ``None`` (no notice, never raises).
    """
    try:
        if kind == "embed":
            from ..embeddings import embedder

            if embedder.is_loaded():
                return None
            return (
                "Loading embedding model (first use). If not cached this downloads "
                "~2.3 GB from HuggingFace once and can take several minutes — set "
                "HF_TOKEN for faster, rate-limit-free downloads."
            )
        if kind == "rerank":
            from ..embeddings import reranker

            if reranker.current_mode() is not None:
                return None
            return (
                "Loading reranker model (first use). If not cached this downloads "
                "~1 GB from HuggingFace once and can take a minute — set HF_TOKEN "
                "for faster, rate-limit-free downloads."
            )
    except Exception:
        return None
    return None
