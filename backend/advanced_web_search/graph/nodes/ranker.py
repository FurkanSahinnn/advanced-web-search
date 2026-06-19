"""
Ranker node — multi-signal scoring + keep/drop decision.

Candidates are grouped by subtopic and scored against that subtopic's question.
Each score breakdown is persisted, streamed to the UI, and merged back into the
candidate dict. Only kept sources flow downstream to synthesis.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...db import repositories
from ...scoring.ranker import score_sources
from ..events import emit


def _dedup_by_id(cands: list[dict]) -> list[dict]:
    """Collapse duplicate candidate dicts by source id (first wins).

    Candidates without an id are kept as-is (cannot be keyed). Idempotent.
    """
    out: list[dict] = []
    seen: set = set()
    for c in cands:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if cid is None:
            out.append(c)
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(c)
    return out


async def ranker(state: dict) -> dict:
    run_id = state["run_id"]
    emit("node_started", run_id, node="ranker", message="Scoring sources")

    # Candidates accumulate across research rounds via the additive reducer, so
    # the same source can appear more than once. Dedup by source id up front so
    # each source is scored once and ranked_sources holds no duplicates.
    raw_candidates = list(state.get("candidates") or [])
    candidates = _dedup_by_id(raw_candidates)
    subtopics = list(state.get("subtopics") or [])
    weights = state.get("weights") or {}
    keep_threshold = float(state.get("keep_threshold", 0.45))

    emit("log", run_id, node="ranker",
         message=f"ranking {len(candidates)} sources (keep>= {keep_threshold})")

    # subtopic_id -> question
    question_of: dict[Any, str] = {}
    for s in subtopics:
        if s.get("id") is not None:
            question_of[s["id"]] = str(s.get("question") or "")

    # group candidates by subtopic_id
    groups: dict[Any, list[dict]] = {}
    for c in candidates:
        groups.setdefault(c.get("subtopic_id"), []).append(c)

    kept_list: list[dict] = []
    errors: list[str] = []

    for subtopic_id, group in groups.items():
        query = question_of.get(subtopic_id, "")
        try:
            results = await score_sources(
                query=query,
                sources=group,
                weights=weights,
                keep_threshold=keep_threshold,
            )
        except Exception as exc:
            errors.append(f"ranker[{subtopic_id}]: score_sources failed: {exc}")
            continue

        # index group by source id for merge
        by_id = {c.get("id"): c for c in group}

        for r in results:
            source_id = r.get("source_id")
            breakdown = r.get("breakdown") or {}
            if source_id is not None:
                try:
                    await asyncio.to_thread(repositories.upsert_score, source_id, breakdown)
                except Exception:
                    pass
            kept = bool(breakdown.get("kept", True))
            emit("source_scored", run_id, node="ranker",
                 source_id=source_id, score=breakdown, kept=kept)
            if kept:
                base = dict(by_id.get(source_id) or {})
                base.update(breakdown)
                base["id"] = source_id
                base["subtopic_id"] = subtopic_id
                kept_list.append(base)

    out: dict = {"ranked_sources": _dedup_by_id(kept_list)}
    if errors:
        out["errors"] = errors
    return out
