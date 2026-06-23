"""
Run lifecycle + SSE bridge.

`run_stream` drives a research run to completion or to the HITL pause, yielding
the custom event frames emitted by the nodes. It is mode-aware:

  * FRESH   — no checkpoint yet: seed `initial_state` and stream from START.
  * PAUSED  — checkpointed at the approval interrupt: resume with the stored
              decision (or re-emit the awaiting_approval frame and stop).
  * DONE     — graph already reached END: emit run_finished and stop.

The interrupt/paused state is detected from the LangGraph state snapshot:
`snap.next` being truthy means the graph is parked at a node (the approval
interrupt) waiting for input.

`approve` stashes the decision for the next `run_stream` resume AND applies it
to the DB immediately so a GET on the project reflects the choice. `cancel`
marks the run cancelled.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from langgraph.types import Command

from .. import config
from ..config import DEFAULT_SCORE_WEIGHTS, get_settings
from ..db import repositories
from ..llm.provider import effective_model_map
from .builder import get_compiled_graph
from .state import initial_state

# run_id -> ApprovalDecision-shaped dict, consumed on the next resume.
_PENDING_DECISIONS: dict[int, dict] = {}

# run_id -> asyncio.Event, set by cancel() to interrupt an in-flight stream in
# THIS process immediately (not only between emitted frames). Registered while a
# run is streaming and removed when the stream ends.
_CANCEL_EVENTS: dict[int, "asyncio.Event"] = {}


def _pending_key(run_id: int) -> str:
    return f"pending_approval:{run_id}"


def _cancel_key(run_id: int) -> str:
    return f"cancel:{run_id}"


def is_cancelled(run_id: int) -> bool:
    """Cooperative-cancel flag, persisted so it survives a process restart."""
    try:
        return bool(repositories.get_setting(_cancel_key(run_id)))
    except Exception:
        return False


def _build_tree(flat: list[dict]) -> list[dict]:
    by_id: dict[Any, dict] = {}
    for s in flat:
        node = dict(s)
        node.setdefault("children", [])
        node["children"] = []
        by_id[node.get("id")] = node
    roots: list[dict] = []
    for node in by_id.values():
        pid = node.get("parent_id")
        if pid is not None and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)
    return roots


def _effective_config() -> dict:
    """Assemble effective run config from persisted settings (DB) over defaults."""
    settings = get_settings()

    weights = repositories.get_setting("weights") or DEFAULT_SCORE_WEIGHTS
    model_map = effective_model_map()

    ra = repositories.get_setting("require_approval")
    require_approval = settings.require_approval if ra is None else bool(ra)

    # --- search-depth preset resolution ---
    depth = repositories.get_setting("depth") or settings.depth
    try:
        preset = config.depth_preset(depth)
    except Exception:
        preset = {}

    def _pick(key: str, fallback):
        """Persisted setting wins; else preset; else the given fallback."""
        v = repositories.get_setting(key)
        if v is not None:
            return v
        if key in preset and preset[key] is not None:
            return preset[key]
        return fallback

    max_subtopics = _pick("max_subtopics", settings.max_subtopics)
    results_per_source = _pick("results_per_source", settings.results_per_source)
    max_sources_per_subtopic = _pick("max_sources_per_subtopic", settings.max_sources_per_subtopic)
    max_research_rounds = _pick("max_research_rounds", settings.max_research_rounds)
    snowball = _pick("snowball", True)
    snowball_top_k = _pick("snowball_top_k", settings.snowball_top_k)
    bilingual = _pick("bilingual", True)

    gap_min_sources = repositories.get_setting("gap_min_sources")
    if gap_min_sources is None:
        gap_min_sources = settings.gap_min_sources
    # query_variants is preset-driven (quick=1 so the fast preset stays single-
    # query; standard/deep/exhaustive=3) with a persisted override still winning.
    query_variants = _pick("query_variants", settings.query_variants)

    keep_threshold = repositories.get_setting("keep_threshold")
    if keep_threshold is None:
        keep_threshold = settings.keep_threshold

    return {
        "weights": dict(weights),
        "model_map": dict(model_map),
        "require_approval": bool(require_approval),
        "max_subtopics": int(max_subtopics),
        "results_per_source": int(results_per_source),
        "keep_threshold": float(keep_threshold),
        "depth": str(depth),
        "max_sources_per_subtopic": int(max_sources_per_subtopic),
        "max_research_rounds": int(max_research_rounds),
        "snowball": bool(snowball),
        "snowball_top_k": int(snowball_top_k),
        "bilingual": bool(bilingual),
        "gap_min_sources": int(gap_min_sources),
        "query_variants": int(query_variants),
    }


async def run_stream(run_id: int) -> AsyncIterator[dict]:
    run = await asyncio.to_thread(repositories.get_run, run_id)
    if not run:
        yield {"type": "error", "run_id": run_id, "data": {"message": "run not found"}}
        return
    project = await asyncio.to_thread(repositories.get_project, run["project_id"])
    if not project:
        yield {"type": "error", "run_id": run_id, "data": {"message": "project not found"}}
        return

    project_id = run["project_id"]
    thread_id = run["thread_id"]

    # A cancelled run is terminal. A stream can be (re-)opened for it without a
    # new run ever starting — the browser's EventSource auto-reconnects after we
    # close the stream, and revisiting the project re-mounts it. Cancelling mid
    # super-step leaves the persisted checkpoint with pending next-tasks, so the
    # PAUSED branch below (driven by snap.next) would otherwise resurrect the run
    # as awaiting_approval. Report cancelled and stop instead — and do NOT clear
    # the flag here, so every reconnect keeps reporting cancelled. (Runs are
    # single-use: a new research always creates a fresh run_id, never re-runs.)
    if run.get("status") == "cancelled" or await asyncio.to_thread(is_cancelled, run_id):
        await asyncio.to_thread(repositories.set_run_status, run_id, "cancelled")
        yield {"type": "run_finished", "run_id": run_id, "data": {"status": "cancelled"}}
        return

    cfg_dict = await asyncio.to_thread(_effective_config)

    graph = await get_compiled_graph()
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    try:
        snap = await graph.aget_state(cfg)
    except Exception as exc:
        yield {"type": "error", "run_id": run_id, "data": {"message": f"state load failed: {exc}"}}
        return

    iterator = None

    if not snap.values:
        # FRESH run.
        # Resolve the selectable report language(s). `report_languages` is stored
        # as a nullable JSON array on the project; a NULL/absent value (older
        # projects) falls back to the single `language` field so the run behaves
        # exactly as before. sanitize_report_languages() keeps only "auto" +
        # supported codes (deduped, capped) and defaults to ["auto"].
        rl_raw = project.get("report_languages")
        try:
            rl_parsed = (
                json.loads(rl_raw)
                if isinstance(rl_raw, str) and rl_raw
                else (rl_raw if isinstance(rl_raw, list) else None)
            )
        except Exception:
            rl_parsed = None
        report_languages = config.sanitize_report_languages(
            rl_parsed or [project.get("language", "auto")]
        )
        inp = initial_state(
            project_id=project_id,
            run_id=run_id,
            thread_id=thread_id,
            root_query=project["root_query"],
            language=project.get("language", "auto"),
            report_languages=report_languages,
            weights=dict(cfg_dict["weights"]),
            model_map=dict(cfg_dict["model_map"]),
            require_approval=cfg_dict["require_approval"],
            max_subtopics=cfg_dict["max_subtopics"],
            results_per_source=cfg_dict["results_per_source"],
            keep_threshold=cfg_dict["keep_threshold"],
            max_sources_per_subtopic=cfg_dict["max_sources_per_subtopic"],
            depth=cfg_dict["depth"],
            max_research_rounds=cfg_dict["max_research_rounds"],
            snowball=cfg_dict["snowball"],
            snowball_top_k=cfg_dict["snowball_top_k"],
            bilingual=cfg_dict["bilingual"],
            gap_min_sources=cfg_dict["gap_min_sources"],
            query_variants=cfg_dict["query_variants"],
        )
        await asyncio.to_thread(repositories.set_run_status, run_id, "running")
        yield {"type": "run_started", "run_id": run_id, "data": {}}
        iterator = graph.astream(inp, cfg, stream_mode="custom")

    elif snap.next:
        # PAUSED at an interrupt (approval). snap.next being truthy is the signal.
        # Prefer the in-memory decision; fall back to the persisted one so a
        # process restart between approve() and this resume still works.
        decision = _PENDING_DECISIONS.pop(run_id, None)
        if decision is None:
            decision = await asyncio.to_thread(repositories.get_setting, _pending_key(run_id))
        if decision is not None:
            # Consume it: clear both the persisted copy and any in-memory copy.
            await asyncio.to_thread(repositories.set_setting, _pending_key(run_id), None)
            _PENDING_DECISIONS.pop(run_id, None)
        if decision is None:
            # No decision yet — re-emit awaiting_approval and stop.
            subtopics = (snap.values or {}).get("subtopics", [])
            tree = _build_tree(subtopics)
            yield {
                "type": "awaiting_approval",
                "run_id": run_id,
                "node": "approval",
                "data": {"subtopics": tree},
            }
            return
        await asyncio.to_thread(repositories.set_run_status, run_id, "running")
        iterator = graph.astream(Command(resume=decision), cfg, stream_mode="custom")

    else:
        # Already reached END.
        yield {"type": "run_finished", "run_id": run_id, "data": {"status": "done"}}
        return

    # Register an in-process cancel signal so a POST /cancel can interrupt the
    # graph promptly — not only between emitted frames. This wakes the loop
    # instantly and aborts the in-flight pull; that tears down work the node is
    # AWAITING (LLM / HTTP). CPU work already handed to a thread (rerank/embed)
    # can't be interrupted and finishes in the background — a bounded (seconds)
    # delay, versus the previously unbounded wait on a long LLM call.
    cancel_event = asyncio.Event()
    _CANCEL_EVENTS[run_id] = cancel_event
    if await asyncio.to_thread(is_cancelled, run_id):
        cancel_event.set()  # a cancel raced in before we registered — honor it
    cancel_wait = asyncio.ensure_future(cancel_event.wait())

    cancelled = False
    nxt = None  # current in-flight pull; hoisted so `finally` can tear it down
    try:
        while True:
            # Pull the next frame as a task so we can race it against a cancel.
            nxt = asyncio.ensure_future(iterator.__anext__())
            await asyncio.wait({nxt, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)

            if not nxt.done():
                # Cancel fired while a node was still working: aborting the pull
                # propagates CancelledError INTO the running node, tearing down
                # the HTTP / LLM call it is AWAITING instead of waiting it out.
                # (Work already in a worker thread runs to completion in the bg.)
                nxt.cancel()
                try:
                    await nxt
                except BaseException:
                    pass
                cancelled = True
                break

            try:
                ev = nxt.result()
            except StopAsyncIteration:
                break
            yield ev

            # A cancel that landed alongside this frame: stop now.
            if cancel_event.is_set():
                cancelled = True
                break
    except asyncio.CancelledError:
        # The SSE client disconnected (uvicorn cancelled us): clean up quietly.
        raise
    except Exception as exc:
        await asyncio.to_thread(repositories.set_run_status, run_id, "error", str(exc))
        yield {"type": "error", "run_id": run_id, "data": {"message": str(exc)}}
        return
    finally:
        cancel_wait.cancel()
        # If we are unwinding with a pull still in flight (e.g. a client
        # disconnect cancels us mid-wait — asyncio.wait does NOT cancel its
        # child tasks), cancel it first: calling aclose() while __anext__ is
        # still running raises "async generator is already running".
        if nxt is not None and not nxt.done():
            nxt.cancel()
            try:
                await nxt
            except BaseException:
                pass
        # Finalize the graph generator so its checkpoint/cleanup runs and no
        # node task is left dangling after we stop pulling.
        try:
            await iterator.aclose()
        except Exception:
            pass
        # Pop ONLY our own Event: if a reconnect for the same run registered a
        # newer one, leave it so cancel() can still reach the live stream.
        if _CANCEL_EVENTS.get(run_id) is cancel_event:
            _CANCEL_EVENTS.pop(run_id, None)

    if cancelled:
        await asyncio.to_thread(repositories.set_run_status, run_id, "cancelled")
        yield {"type": "run_finished", "run_id": run_id, "data": {"status": "cancelled"}}
        return

    # A cancel may have arrived after the last frame but before the graph ended.
    if await asyncio.to_thread(is_cancelled, run_id):
        await asyncio.to_thread(repositories.set_run_status, run_id, "cancelled")
        yield {"type": "run_finished", "run_id": run_id, "data": {"status": "cancelled"}}
        return

    # After the loop: if still parked at the approval interrupt, mark the run.
    try:
        snap2 = await graph.aget_state(cfg)
        if snap2.next:
            await asyncio.to_thread(repositories.set_run_status, run_id, "awaiting_approval")
    except Exception:
        pass


async def approve(run_id: int, decision: dict) -> None:
    """Stash the decision for resume AND apply it to the DB immediately."""
    decision = decision or {}
    _PENDING_DECISIONS[run_id] = decision
    # Also persist it so a process restart between approve() and the next
    # run_stream resume does not lose the decision.
    await asyncio.to_thread(repositories.set_setting, _pending_key(run_id), decision)

    run = await asyncio.to_thread(repositories.get_run, run_id)
    if not run:
        return
    project_id = run["project_id"]

    edits = decision.get("approved_subtopics") or []
    kept_ids: set[int] = set()
    deleted_ids: set[int] = set()
    for e in edits:
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not isinstance(eid, int) or eid <= 0:
            continue
        if e.get("keep", True):
            kept_ids.add(eid)
        else:
            deleted_ids.add(eid)

    try:
        await asyncio.to_thread(
            repositories.set_subtopic_approval, project_id, kept_ids, deleted_ids
        )
    except Exception:
        pass
    await asyncio.to_thread(repositories.set_run_status, run_id, "running")


async def cancel(run_id: int) -> None:
    # Persist a cooperative-cancel flag (reconnect-safe), and mark the run
    # cancelled immediately so a GET reflects the choice even before the
    # in-flight stream notices.
    await asyncio.to_thread(repositories.set_setting, _cancel_key(run_id), True)
    await asyncio.to_thread(repositories.set_run_status, run_id, "cancelled")
    # Wake any in-flight stream for this run so it aborts the graph NOW rather
    # than at the next emitted frame (same event loop — set() is enough).
    ev = _CANCEL_EVENTS.get(run_id)
    if ev is not None:
        ev.set()
