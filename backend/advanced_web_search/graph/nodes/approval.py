"""
Approval node — human-in-the-loop gate.

When approval is not required, every subtopic is auto-approved. Otherwise the
node emits the subtopic tree, then `interrupt(...)`s the graph so the API layer
can collect an ApprovalDecision. On resume the decision is applied: kept nodes
survive (with optional question/perspective edits), unkept nodes are deleted,
and newly-added nodes (id<0) are inserted. The decomposition is re-persisted
via replace_subtopics so all ids are fresh.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from langgraph.types import interrupt

from ...db import repositories
from ..events import emit


def _build_tree(flat: list[dict]) -> list[dict]:
    """Nest a flat subtopic list by parent_id. Returns top-level nodes."""
    by_id: dict[Any, dict] = {}
    for s in flat:
        node = dict(s)
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


async def approval(state: dict) -> dict:
    run_id = state["run_id"]
    project_id = state["project_id"]
    subtopics = list(state.get("subtopics") or [])

    emit("node_started", run_id, node="approval", message="Approval gate")

    # --- auto-approve path ---
    if not state.get("require_approval"):
        all_ids = {s["id"] for s in subtopics if s.get("id") is not None}
        try:
            await asyncio.to_thread(
                repositories.set_subtopic_approval, project_id, all_ids, set()
            )
        except Exception:
            pass
        approved = [{**s, "approved": True} for s in subtopics]
        emit("subtopic", run_id, node="approval", message="Auto-approved",
             count=len(approved))
        return {"subtopics": approved}

    # --- HITL path: emit the tree and pause ---
    tree = _build_tree(subtopics)
    emit("awaiting_approval", run_id, node="approval",
         message="Awaiting human approval", subtopics=tree)

    decision = interrupt({"subtopics": tree})
    if not isinstance(decision, dict):
        decision = {}

    edits = decision.get("approved_subtopics") or []
    extra_instructions = decision.get("extra_instructions") or ""

    existing = {s.get("id"): s for s in subtopics if s.get("id") is not None}

    # Build the kept + new node list for replace_subtopics. Items with keep=False
    # are dropped; id>0 are existing (kept, possibly edited); id<0 are new.
    nodes: list[dict] = []
    ordc = 0
    for e in edits:
        if not isinstance(e, dict):
            continue
        if not e.get("keep", True):
            continue
        eid = e.get("id")
        question = str(e.get("question") or "").strip()
        parent_id = e.get("parent_id")
        if eid is not None and eid > 0:
            base = existing.get(eid, {})
            q = question or str(base.get("question") or "")
            persp = e.get("perspective")
            if persp is None:
                persp = base.get("perspective")
            depth = int(base.get("depth", 0) or 0)
            nodes.append({
                "temp_id": eid,
                "parent_temp_id": parent_id,
                "question": q,
                "perspective": persp,
                "rationale": base.get("rationale"),
                "depth": depth,
                "ord": ordc,
                "approved": True,
            })
        else:
            # newly added node (id<0). Use its own id as a distinct temp key.
            temp = eid if eid is not None else f"new-{ordc}"
            nodes.append({
                "temp_id": temp,
                "parent_temp_id": parent_id,
                "question": question,
                "perspective": e.get("perspective"),
                "rationale": None,
                "depth": 1 if parent_id else 0,
                "ord": ordc,
                "approved": True,
            })
        ordc += 1

    if not nodes:
        # User rejected everything — keep the original plan approved so the run can proceed.
        for s in subtopics:
            nodes.append({
                "temp_id": s.get("id"),
                "parent_temp_id": s.get("parent_id"),
                "question": s.get("question"),
                "perspective": s.get("perspective"),
                "rationale": s.get("rationale"),
                "depth": int(s.get("depth", 0) or 0),
                "ord": int(s.get("ord", 0) or 0),
                "approved": True,
            })

    try:
        persisted = await asyncio.to_thread(repositories.replace_subtopics, project_id, nodes)
    except Exception as exc:
        approved = [{**s, "approved": True} for s in subtopics]
        return {"subtopics": approved, "extra_instructions": extra_instructions,
                "errors": [f"approval: replace_subtopics failed: {exc}"]}

    approved_list: list[dict] = []
    for p in persisted:
        approved_list.append({
            "id": p["id"],
            "parent_id": p.get("parent_id"),
            "question": p.get("question"),
            "perspective": p.get("perspective"),
            "rationale": p.get("rationale"),
            "depth": int(p.get("depth", 0) or 0),
            "ord": int(p.get("ord", 0) or 0),
            "approved": True,
            "status": "pending",
        })

    return {"subtopics": approved_list, "extra_instructions": extra_instructions}
