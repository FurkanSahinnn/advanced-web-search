"""
Graph assembly + compilation.

Wires the eight research nodes into a StateGraph over ResearchState with a
single conditional edge: after verification, loop back to the synthesizer when
a fatal (all-citations-dead) claim survives and we are under the iteration cap,
otherwise finalize.

A single process-wide AsyncSqliteSaver (backed by one long-lived aiosqlite
connection) provides checkpointing so runs are resumable across the HITL
interrupt. The compiled graph is cached as a module singleton.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from .nodes import (
    approval,
    finalizer,
    gap_analyzer,
    moderator,
    planner,
    ranker,
    researcher,
    synthesizer,
    verifier,
)
from .state import ResearchState

_compiled = None
_conn = None
_saver = None
_lock = asyncio.Lock()


def route_after_verify(state: ResearchState) -> str:
    """Loop back to synthesis on a fatal verdict, else finalize."""
    return "synthesizer" if state.get("verifier_fatal") else "finalizer"


def route_after_gap(state: ResearchState) -> str:
    """Loop back to the researcher for another round, else proceed to synthesis.

    The gap node itself enforces the ``max_research_rounds`` cap (it only sets
    ``needs_more_research`` while under the cap), so this edge can never loop
    forever — on any gap-node failure it returns False and we synthesize.
    """
    return "researcher" if state.get("needs_more_research") else "synthesizer"


def _build_state_graph():
    g = StateGraph(ResearchState)

    g.add_node("planner", planner)
    g.add_node("moderator", moderator)
    g.add_node("approval", approval)
    g.add_node("researcher", researcher)
    g.add_node("ranker", ranker)
    g.add_node("gap_analyzer", gap_analyzer)
    g.add_node("synthesizer", synthesizer)
    g.add_node("verifier", verifier)
    g.add_node("finalizer", finalizer)

    g.add_edge(START, "planner")
    g.add_edge("planner", "moderator")
    g.add_edge("moderator", "approval")
    g.add_edge("approval", "researcher")
    g.add_edge("researcher", "ranker")
    # iterative gap-driven loop: ranker -> gap_analyzer -> (researcher | synthesizer)
    g.add_edge("ranker", "gap_analyzer")
    g.add_conditional_edges(
        "gap_analyzer",
        route_after_gap,
        {"researcher": "researcher", "synthesizer": "synthesizer"},
    )
    g.add_edge("synthesizer", "verifier")
    g.add_conditional_edges(
        "verifier",
        route_after_verify,
        {"synthesizer": "synthesizer", "finalizer": "finalizer"},
    )
    g.add_edge("finalizer", END)
    return g


async def reset() -> None:
    """Drop the cached compiled graph + checkpointer singleton.

    Test-support hook: the compiled graph, its AsyncSqliteSaver and the backing
    aiosqlite connection are bound to the event loop they were created in. Tests
    that run each case in a fresh loop (and/or a fresh temp DB) must drop these
    so the next ``get_compiled_graph()`` rebuilds them in the current loop.
    """
    global _compiled, _conn, _saver
    conn = _conn
    _compiled = None
    _saver = None
    _conn = None
    if conn is not None:
        try:
            await conn.close()
        except Exception:
            pass


async def get_compiled_graph():
    """Return the process-wide compiled graph (built once, then cached)."""
    global _compiled, _conn, _saver
    if _compiled is not None:
        return _compiled

    async with _lock:
        if _compiled is not None:
            return _compiled

        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = str(get_settings().db_path)
        # A single shared connection kept alive for the whole process lifetime.
        _conn = await aiosqlite.connect(db_path)
        _saver = AsyncSqliteSaver(_conn)
        await _saver.setup()

        graph = _build_state_graph()
        _compiled = graph.compile(checkpointer=_saver)
        return _compiled
