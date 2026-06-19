"""
Planner node — STORM-style decomposition of the root query.

Asks the planner model to break the root question into a tree of nested
sub-questions, each carrying a persona/angle (perspective) and a rationale.
The decomposition is persisted via repositories.replace_subtopics (which
reassigns real ids) and streamed to the UI one subtopic at a time.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...db import repositories
from ...llm.provider import chat_json
from ...utils.text import detect_language, truncate
from ..events import emit


async def planner(state: dict) -> dict:
    run_id = state["run_id"]
    project_id = state["project_id"]
    root_query = state.get("root_query", "")
    emit("node_started", run_id, node="planner", message="Decomposing the research question")

    errors: list[str] = []

    # --- resolve language ---
    language = state.get("language", "auto")
    if language == "auto":
        try:
            language = detect_language(root_query) or "en"
        except Exception:
            language = "en"

    max_subtopics = int(state.get("max_subtopics", 12))

    system = (
        "You are the Planner of a multi-agent deep-research system. You apply a "
        "STORM-style decomposition: break a root research question into a TREE of "
        "focused, non-overlapping sub-questions, each explored from a distinct "
        "angle or persona (its 'perspective')."
    )
    user = (
        f"ROOT QUESTION:\n{root_query}\n\n"
        f"Decompose this into at most {max_subtopics} nested sub-questions that "
        "together comprehensively answer the root question.\n\n"
        "Return ONLY a JSON array. Each element is an object:\n"
        '  {"question": str, "perspective": str (a STORM-style angle/persona), '
        '"rationale": str, "parent": int|null (0-based index into THIS array of '
        'the parent question, or null for a top-level node), "depth": int}\n\n'
        "Rules:\n"
        "- A parent index MUST refer to an EARLIER element in the array.\n"
        "- Top-level nodes have parent=null and depth=0.\n"
        f"- Reply in this LANGUAGE: {language}.\n"
        "- Output the JSON array only, no prose, no code fences."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    raw: Any = None
    try:
        raw = await chat_json("planner", messages)
    except Exception as exc:  # defensive: never crash the run
        errors.append(f"planner: chat_json failed: {exc}")
        raw = None

    items = _coerce_list(raw)
    if not items:
        # Degrade gracefully: at least research the root question itself.
        errors.append("planner: empty/invalid plan; falling back to root query")
        items = [{"question": root_query, "perspective": "general overview",
                  "rationale": "root question", "parent": None, "depth": 0}]

    items = items[:max_subtopics]

    # --- build node list for replace_subtopics ---
    nodes: list[dict] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        parent = it.get("parent")
        parent_temp = None
        if isinstance(parent, int) and 0 <= parent < len(items) and parent != i:
            parent_temp = parent
        question = str(it.get("question") or "").strip()
        if not question:
            continue
        depth = it.get("depth")
        try:
            depth = int(depth)
        except Exception:
            depth = 0 if parent_temp is None else 1
        nodes.append({
            "temp_id": i,
            "parent_temp_id": parent_temp,
            "question": truncate(question, 800),
            "perspective": (str(it.get("perspective")).strip() if it.get("perspective") else None),
            "rationale": (str(it.get("rationale")).strip() if it.get("rationale") else None),
            "depth": max(0, depth),
            "ord": i,
        })

    if not nodes:
        nodes = [{
            "temp_id": 0, "parent_temp_id": None,
            "question": truncate(root_query, 800), "perspective": "general overview",
            "rationale": "root question", "depth": 0, "ord": 0,
        }]

    # replace_subtopics retries transient WAL-writer collisions with the
    # checkpointer internally (db.run_in_tx), so a transient lock no longer
    # silently drops the decomposition to zero subtopics.
    try:
        persisted = await asyncio.to_thread(repositories.replace_subtopics, project_id, nodes)
    except Exception as exc:
        errors.append(f"planner: replace_subtopics failed: {exc}")
        return {"language": language, "errors": errors}

    subtopics: list[dict] = []
    for p in persisted:
        st = {
            "id": p["id"],
            "parent_id": p.get("parent_id"),
            "question": p.get("question"),
            "perspective": p.get("perspective"),
            "rationale": p.get("rationale"),
            "depth": int(p.get("depth", 0) or 0),
            "ord": int(p.get("ord", 0) or 0),
            "approved": False,
            "status": "pending",
        }
        subtopics.append(st)

    emit("plan", run_id, node="planner", message="Plan ready", count=len(subtopics))
    for st in subtopics:
        emit("subtopic", run_id, node="planner", subtopic=st)

    out: dict = {"subtopics": subtopics, "language": language}
    if errors:
        out["errors"] = errors
    return out


def _coerce_list(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # common wrappers
        for key in ("subtopics", "questions", "items", "nodes", "plan", "tree"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        # a single node object
        if "question" in raw:
            return [raw]
        return []
    if isinstance(raw, str):
        try:
            return _coerce_list(json.loads(raw))
        except Exception:
            return []
    return []
