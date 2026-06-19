"""
Moderator node — Co-STORM gap pass.

Looks at the current set of sub-questions and proposes up to 3 ADDITIONAL
under-covered angles, appended as new top-level subtopics (keeping the total
within max_subtopics). The full set is re-persisted so the new nodes receive
real ids. On any failure this node is a no-op (returns {}).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...db import repositories
from ...llm.provider import chat_json
from ...utils.text import truncate
from ..events import emit


async def moderator(state: dict) -> dict:
    run_id = state["run_id"]
    project_id = state["project_id"]
    language = state.get("language", "en")
    max_subtopics = int(state.get("max_subtopics", 12))
    current = list(state.get("subtopics") or [])

    emit("node_started", run_id, node="moderator", message="Scanning for coverage gaps")

    if not current or len(current) >= max_subtopics:
        return {}

    questions = [str(s.get("question") or "") for s in current if s.get("question")]
    listing = "\n".join(f"- {q}" for q in questions)

    remaining = max_subtopics - len(current)
    n = min(3, remaining)

    system = (
        "You are the Moderator of a Co-STORM multi-agent research process. Your job "
        "is to find IMPORTANT angles that the current question set under-covers and "
        "propose new, non-redundant sub-questions."
    )
    user = (
        f"CURRENT SUB-QUESTIONS:\n{listing}\n\n"
        f"Propose up to {n} ADDITIONAL under-covered angles that are NOT already "
        "covered above. Return ONLY a JSON array of objects:\n"
        '  {"question": str, "perspective": str, "rationale": str}\n'
        f"Reply in this LANGUAGE: {language}. Output the JSON array only."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    try:
        raw = await chat_json("moderator", messages)
    except Exception:
        return {}

    extra = _coerce_list(raw)
    if not extra:
        return {}

    new_items: list[dict] = []
    for it in extra:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or "").strip()
        if not q:
            continue
        new_items.append({
            "question": truncate(q, 800),
            "perspective": (str(it.get("perspective")).strip() if it.get("perspective") else None),
            "rationale": (str(it.get("rationale")).strip() if it.get("rationale") else None),
        })
        if len(new_items) >= n:
            break

    if not new_items:
        return {}

    # --- rebuild full node list: existing (old id -> temp_id) + appended new top-level nodes ---
    nodes: list[dict] = []
    for s in current:
        old_id = s.get("id")
        if old_id is None:
            continue
        nodes.append({
            "temp_id": old_id,
            "parent_temp_id": s.get("parent_id"),
            "question": s.get("question"),
            "perspective": s.get("perspective"),
            "rationale": s.get("rationale"),
            "depth": int(s.get("depth", 0) or 0),
            "ord": int(s.get("ord", 0) or 0),
            "approved": bool(s.get("approved")),
        })

    base_ord = len(nodes)
    for j, it in enumerate(new_items):
        nodes.append({
            "temp_id": f"new-{j}",
            "parent_temp_id": None,
            "question": it["question"],
            "perspective": it["perspective"],
            "rationale": it["rationale"],
            "depth": 1,
            "ord": base_ord + j,
            "approved": False,
        })

    new_questions = {it["question"] for it in new_items}

    try:
        persisted = await asyncio.to_thread(repositories.replace_subtopics, project_id, nodes)
    except Exception:
        return {}

    updated: list[dict] = []
    new_emitted: list[dict] = []
    for p in persisted:
        st = {
            "id": p["id"],
            "parent_id": p.get("parent_id"),
            "question": p.get("question"),
            "perspective": p.get("perspective"),
            "rationale": p.get("rationale"),
            "depth": int(p.get("depth", 0) or 0),
            "ord": int(p.get("ord", 0) or 0),
            "approved": bool(p.get("approved")),
            "status": "pending",
        }
        updated.append(st)
        if p.get("question") in new_questions and (p.get("depth", 0) or 0) == 1:
            new_emitted.append(st)

    for st in new_emitted:
        emit("subtopic", run_id, node="moderator", subtopic=st)

    return {"subtopics": updated}


def _coerce_list(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("subtopics", "questions", "items", "angles", "gaps"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        if "question" in raw:
            return [raw]
        return []
    if isinstance(raw, str):
        try:
            return _coerce_list(json.loads(raw))
        except Exception:
            return []
    return []
