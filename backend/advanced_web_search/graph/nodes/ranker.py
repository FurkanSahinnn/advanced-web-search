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
from ...embeddings import reranker
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
    scored_any = False
    # Per-subtopic absolute rerank confidence (mean of the top-k sources'
    # batch-independent cross-encoder relevance prob), surfaced to the gap node
    # for CRAG sufficiency grading. Keyed by str(subtopic_id) so it stays
    # msgpack/JSON-safe in the checkpointed state. Empty when the reranker is in
    # identity/degraded mode (no absolute signal) — the gap node then falls back
    # to the source-count proxy.
    rerank_confidence: dict[str, float] = {}

    for subtopic_id, group in groups.items():
        query = question_of.get(subtopic_id, "")
        try:
            results = await score_sources(
                query=query,
                sources=group,
                weights=weights,
                keep_threshold=keep_threshold,
            )
            scored_any = True
        except Exception as exc:
            errors.append(f"ranker[{subtopic_id}]: score_sources failed: {exc}")
            continue

        # Aggregate the absolute rerank confidence for this subtopic: the mean of
        # the top-3 sources' rerank_abs answers "did retrieval surface at least a
        # few genuinely on-topic documents?" — robust to one strong source and to
        # a long tail of weak ones. Absent unless a real cross-encoder ran.
        abs_vals = [
            float(v)
            for r in results
            if isinstance((v := ((r.get("breakdown") or {}).get("detail") or {})
                           .get("rerank_abs")), (int, float))
        ]
        if abs_vals and subtopic_id is not None:
            abs_vals.sort(reverse=True)
            top = abs_vals[:3]
            rerank_confidence[str(subtopic_id)] = round(sum(top) / len(top), 4)

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

    # Surface a silent quality collapse: if scoring ran the reranker but it had
    # degraded to identity mode, the dominant 0.40 relevance signal was just
    # provider order. Read the mode AFTER scoring (a no-op load-free check) and
    # tell the trace + the report scorecard so the drop isn't invisible. Gate on
    # scored_any so a run where every group failed to score (reranker never
    # invoked) isn't mislabeled as degraded.
    degraded = scored_any and reranker.current_mode() == "identity"
    if degraded:
        emit("log", run_id, node="ranker",
             message="reranker unavailable — relevance ranking degraded to source order",
             degraded=True)

    out: dict = {"ranked_sources": _dedup_by_id(kept_list), "reranker_degraded": degraded}
    if rerank_confidence:
        out["rerank_confidence"] = rerank_confidence
    if errors:
        out["errors"] = errors
    return out
