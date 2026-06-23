"""
LangGraph shared state contract.

The graph is a StateGraph over `ResearchState`. Parallel researcher
branches (dispatched with the Send API) return partial states whose
`candidates` and `errors` lists are merged via additive reducers.

Node order (see graph/builder.py):

    planner -> moderator -> approval(interrupt) -> researcher(fan-out)
        -> ranker -> synthesizer -> verifier
        -> (loop back to synthesizer if FATAL, capped) -> finalizer

Every node should:
  * read what it needs from state and return ONLY the keys it changes,
  * emit ResearchEvent frames via graph/events.py `emit(...)`,
  * persist durable artifacts (subtopics, sources, scores, claims, report)
    through repositories so the SQLite db is the source of truth,
  * be resumable (the SqliteSaver checkpoints state between supersteps).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _add(a: list | None, b: list | None) -> list:
    return (a or []) + (b or [])


class ResearchState(TypedDict, total=False):
    # --- identity / config (set at run start, read-only thereafter) ---
    project_id: int
    run_id: int
    thread_id: str
    root_query: str
    language: str               # 'auto' | 'tr' | 'en' | ... (search hint)
    report_languages: list[str]  # report output langs (menu: 'auto' + supported codes)
    weights: dict[str, float]   # ScoreWeights as dict
    model_map: dict[str, str]   # per-agent model ids
    require_approval: bool
    max_subtopics: int
    results_per_source: int
    keep_threshold: float
    max_sources_per_subtopic: int

    # --- comprehensiveness / deep-search config ---
    depth: str
    max_research_rounds: int
    snowball: bool
    snowball_top_k: int
    bilingual: bool
    gap_min_sources: int
    query_variants: int

    # --- iterative-loop bookkeeping ---
    research_round: int
    researched_subtopic_ids: Annotated[list[int], _add]
    gap_subtopic_ids: list[int]            # sub-questions to (re)search this round
    snowball_seed_ids: list[int]           # source ids to expand citations from
    needs_more_research: bool
    # Entailment-driven re-research: subtopics whose claims the verifier found
    # unsupported by their cited sources, routed back to the researcher to find
    # evidence that actually backs (or refutes) them. `reresearch_subtopic_ids`
    # is the queue for the next pass; `reresearched_subtopic_ids` accumulates the
    # ones already retried so a subtopic is re-researched at most once (no thrash).
    reresearch_subtopic_ids: list[int]
    reresearched_subtopic_ids: Annotated[list[int], _add]

    # --- planning ---
    subtopics: list[dict[str, Any]]   # flat nodes: {id,parent_id,question,perspective,approved,depth,ord}
    extra_instructions: str           # appended by the HITL approval step

    # --- retrieval (parallel fan-out merges here) ---
    candidates: Annotated[list[dict[str, Any]], operator.add]

    # --- ranking ---
    ranked_sources: list[dict[str, Any]]   # kept sources with score breakdown
    # True when the cross-encoder reranker degraded to identity mode this run, so
    # the dominant relevance signal collapsed to provider order. Surfaced in the
    # trace + the report quality scorecard so the quality drop isn't silent.
    reranker_degraded: bool
    # Per-subtopic absolute rerank confidence {str(subtopic_id): float in [0,1]},
    # written by the ranker, read by the gap node's CRAG sufficiency grade.
    # Recomputed over ALL candidates each ranker pass (candidates accumulate), so
    # last-write-wins is complete each pass. Empty when the reranker is degraded.
    rerank_confidence: dict[str, float]

    # --- synthesis ---
    claims: list[dict[str, Any]]           # {text, subtopic_id, citations:[{source_id,...}]}
    report_markdown: str
    consensus_summary: str
    disagreements: str
    comprehensiveness: float
    certainty: float

    # --- verification loop ---
    verifier_iteration: int
    verifier_fatal: bool
    verifier_needs_evidence: bool          # route verifier -> researcher for re-research
    verifier_notes: list[dict[str, Any]]

    # --- bookkeeping ---
    errors: Annotated[list[str], _add]


def initial_state(
    *,
    project_id: int,
    run_id: int,
    thread_id: str,
    root_query: str,
    language: str,
    report_languages: list[str] | None = None,
    weights: dict[str, float],
    model_map: dict[str, str],
    require_approval: bool,
    max_subtopics: int,
    results_per_source: int,
    keep_threshold: float,
    max_sources_per_subtopic: int = 25,
    depth: str = "quick",
    max_research_rounds: int = 3,
    snowball: bool = True,
    snowball_top_k: int = 8,
    bilingual: bool = True,
    gap_min_sources: int = 3,
    query_variants: int = 3,
) -> ResearchState:
    return ResearchState(
        project_id=project_id,
        run_id=run_id,
        thread_id=thread_id,
        root_query=root_query,
        language=language,
        report_languages=report_languages or ["auto"],
        weights=weights,
        model_map=model_map,
        require_approval=require_approval,
        max_subtopics=max_subtopics,
        results_per_source=results_per_source,
        keep_threshold=keep_threshold,
        max_sources_per_subtopic=max_sources_per_subtopic,
        depth=depth,
        max_research_rounds=max_research_rounds,
        snowball=snowball,
        snowball_top_k=snowball_top_k,
        bilingual=bilingual,
        gap_min_sources=gap_min_sources,
        query_variants=query_variants,
        research_round=0,
        researched_subtopic_ids=[],
        gap_subtopic_ids=[],
        snowball_seed_ids=[],
        needs_more_research=False,
        reresearch_subtopic_ids=[],
        reresearched_subtopic_ids=[],
        subtopics=[],
        extra_instructions="",
        candidates=[],
        ranked_sources=[],
        reranker_degraded=False,
        rerank_confidence={},
        claims=[],
        report_markdown="",
        consensus_summary="",
        disagreements="",
        comprehensiveness=0.0,
        certainty=0.0,
        verifier_iteration=0,
        verifier_fatal=False,
        verifier_needs_evidence=False,
        verifier_notes=[],
        errors=[],
    )
