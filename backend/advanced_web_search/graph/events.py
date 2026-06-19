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
