"""
Gap-analyzer node — iterative, gap-driven follow-up research.

After each ranker pass this node decides whether another research round is
worthwhile and, if so, what that round should do:

  * Under-covered sub-questions (fewer than ``gap_min_sources`` kept sources)
    trigger the planner model to propose 1-3 NEW, more specific follow-up
    sub-questions which are persisted as approved child subtopics. Their ids
    go into ``gap_subtopic_ids`` for the researcher's next round.

  * Once per run (round 1) the top academic kept sources are selected as
    ``snowball_seed_ids`` so the researcher can expand their citations.

Continuation is hard-bounded by ``max_research_rounds`` so the loop always
terminates. On ANY exception the node returns ``needs_more_research=False`` so
the graph proceeds straight to synthesis.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...config import depth_preset
from ...db import repositories
from ...llm.provider import chat_json
from ...utils.text import truncate
from ..events import emit

# Absolute ceiling on the total number of subtopics, so repeated rounds can
# never let the decomposition grow without bound.
_MAX_TOTAL_SUBTOPICS = 40
_MAX_NEW_SUBTOPICS = 3

# Corrective-RAG (CRAG, 2401.15884) sufficiency thresholds on a sub-question's
# absolute rerank confidence (mean top-k cross-encoder relevance prob from the
# ranker). >= SUFFICIENT = "Correct" (retrieval is strong, no follow-up needed);
# < WEAK = "Incorrect" (off-topic/empty, needs a targeted rewrite); in between =
# "Ambiguous" (also worth a follow-up). Only consulted when a real cross-encoder
# produced a confidence; otherwise the gap node falls back to the count proxy.
_CRAG_SUFFICIENT = 0.55
_CRAG_WEAK = 0.30

# Dynamic outline revision: at most this many NET-NEW angles the retrieved
# sources reveal (but the planner missed) may be added in one round-1 pass.
_MAX_OUTLINE_ADD = 2

_ACADEMIC_PROVIDERS = {
    "openalex", "openalex-snowball", "arxiv", "crossref", "europepmc",
    "semanticscholar", "semantic_scholar", "doaj", "unpaywall",
}


def _leaf_approved(subtopics: list[dict]) -> list[dict]:
    """Approved subtopics that are not a parent of another approved subtopic."""
    approved = [s for s in subtopics if s.get("approved")]
    if not approved:
        approved = list(subtopics)
    ids = {s.get("id") for s in approved}
    parent_ids = {s.get("parent_id") for s in approved if s.get("parent_id") in ids}
    leaves = [s for s in approved if s.get("id") not in parent_ids]
    return leaves or approved


def _is_academic(src: dict) -> bool:
    prov = (src.get("provider") or "").lower()
    if prov in _ACADEMIC_PROVIDERS:
        return True
    if (src.get("kind") or "") == "academic":
        return True
    cid = src.get("canonical_id") or ""
    return isinstance(cid, str) and (cid.startswith("doi:") or cid.startswith("arxiv:"))


def _grade_coverage(
    leaves: list[dict],
    counts: dict[Any, int],
    gap_min: int,
    crag_on: bool,
    confidence: dict[str, float],
    reranker_degraded: bool,
) -> tuple[list[dict], dict[Any, str], bool]:
    """Decide which leaf sub-questions need a follow-up round (CRAG-aware).

    Returns ``(under_covered, grades, all_sufficient)``:

      * ``under_covered`` — leaves to send the moderator for a targeted follow-up.
      * ``grades``        — ``{subtopic_id: label}`` for the trace log.
      * ``all_sufficient``— True iff CRAG actually graded EVERY leaf and none came
                            back weak/ambiguous (drives the gap-loop early-exit).

    When CRAG is on AND a real rerank confidence exists for a leaf with sources,
    grade by that absolute confidence (Correct / Ambiguous / Incorrect). Else —
    CRAG off, reranker degraded, no confidence, or a zero-source leaf — fall back
    to the historical kept-source COUNT proxy (``count < gap_min``) so behaviour
    never regresses when the cross-encoder is unavailable.
    """
    under: list[dict] = []
    grades: dict[Any, str] = {}
    crag_graded = 0
    for s in leaves:
        sid = s.get("id")
        cnt = counts.get(sid, 0)
        conf = confidence.get(str(sid)) if isinstance(confidence, dict) else None
        use_crag = (
            crag_on and not reranker_degraded
            and isinstance(conf, (int, float)) and cnt > 0
        )
        if use_crag:
            crag_graded += 1
            if conf >= _CRAG_SUFFICIENT:
                grades[sid] = "sufficient"
            elif conf < _CRAG_WEAK:
                grades[sid] = "weak"
                under.append(s)
            else:
                grades[sid] = "ambiguous"
                under.append(s)
        else:
            if cnt < gap_min:
                grades[sid] = "under"
                under.append(s)
            else:
                grades[sid] = "covered"
    # Early-exit is only justified when CRAG graded the WHOLE tree (no leaf fell
    # back to the count proxy) and nothing needs a follow-up.
    all_sufficient = crag_graded == len(leaves) and crag_graded > 0 and not under
    return under, grades, all_sufficient


async def gap_analyzer(state: dict) -> dict:
    run_id = state["run_id"]
    emit("node_started", run_id, node="gap_analyzer", message="Analyzing coverage gaps")

    try:
        project_id = state["project_id"]
        language = state.get("language", "auto")
        research_round = int(state.get("research_round", 0) or 0)
        max_rounds = int(state.get("max_research_rounds", 1) or 1)
        gap_min = int(state.get("gap_min_sources", 3) or 3)
        snowball_on = bool(state.get("snowball"))
        snowball_top_k = int(state.get("snowball_top_k", 0) or 0)
        preset = depth_preset(state.get("depth"))
        crag_on = bool(preset.get("crag", False))
        outline_on = bool(preset.get("outline_revision", False))
        confidence = state.get("rerank_confidence") or {}
        reranker_degraded = bool(state.get("reranker_degraded"))

        ranked = list(state.get("ranked_sources") or [])
        subtopics = list(state.get("subtopics") or [])

        # --- kept-source count per subtopic ---
        counts: dict[Any, int] = {}
        for s in ranked:
            sid = s.get("subtopic_id")
            counts[sid] = counts.get(sid, 0) + 1

        leaves = _leaf_approved(subtopics)
        # CRAG sufficiency grade (rerank-confidence based) with a count-proxy
        # fallback; `all_sufficient` lets the loop exit early when retrieval is
        # already strong instead of always burning the round budget.
        under_covered, grades, all_sufficient = _grade_coverage(
            leaves, counts, gap_min, crag_on, confidence, reranker_degraded
        )
        if crag_on and grades:
            graded_str = ", ".join(
                f"{counts.get(s.get('id'), 0)}src/"
                f"{int((confidence.get(str(s.get('id'))) or 0) * 100)}%"
                f"={grades.get(s.get('id'), '?')}"
                for s in leaves[:8]
            )
            emit("log", run_id, node="gap_analyzer",
                 message=f"CRAG grades [{graded_str}]"
                         + (" — all sufficient" if all_sufficient else ""))

        # --- HARD STOP: never exceed the configured round cap ---
        if research_round >= max_rounds:
            emit("log", run_id, node="gap_analyzer",
                 message=f"Round {research_round}: research-round cap reached; finalizing.")
            return {"needs_more_research": False}

        # --- CRAG early-exit: retrieval is already strong everywhere, so don't
        # spend another round just because the budget allows it. BUT never let it
        # pre-empt the one-shot round-1 passes (snowball + outline revision) — those
        # are independently useful and their knobs are independently overridable, so
        # the early-exit must not silently swallow them. ---
        snowball_pending = snowball_on and snowball_top_k > 0 and research_round == 1
        outline_pending = outline_on and research_round == 1
        if all_sufficient and not (snowball_pending or outline_pending):
            emit("log", run_id, node="gap_analyzer",
                 message=f"Round {research_round}: CRAG — all sub-questions "
                         "sufficiently covered; finalizing early.")
            return {"needs_more_research": False}

        gap_subtopic_ids: list[int] = []
        new_subtopic_count = 0
        updated_subtopics: list[dict] = []

        # --- 1) build follow-up sub-questions for the biggest gaps ---
        if under_covered and len(subtopics) < _MAX_TOTAL_SUBTOPICS:
            new_nodes = await _propose_followups(
                state, under_covered, counts, language, grades
            )
            if new_nodes:
                persisted_new = await _persist_new_subtopics(
                    project_id, subtopics, new_nodes
                )
                for st in persisted_new:
                    gap_subtopic_ids.append(int(st["id"]))
                    updated_subtopics.append(st)
                    new_subtopic_count += 1
                    emit("subtopic", run_id, node="gap_analyzer", subtopic=st)

        # --- 1b) dynamic outline revision (content-driven, round 1 only) ---
        # Add net-new angles the retrieved corpus reveals but the planner missed.
        # One-shot (round 1) + additive + deduped, so the outline can grow toward
        # the evidence without the gap loop oscillating across rounds.
        total_now = len(subtopics) + len(updated_subtopics)
        if outline_on and research_round == 1 and total_now < _MAX_TOTAL_SUBTOPICS:
            existing_q = {_norm_q(str(s.get("question") or "")) for s in subtopics}
            existing_q |= {_norm_q(str(s.get("question") or "")) for s in updated_subtopics}
            revisions = await _propose_outline_revisions(
                state, ranked, existing_q, language
            )
            if revisions:
                persisted_rev = await _persist_new_subtopics(
                    project_id, subtopics + updated_subtopics, revisions
                )
                for st in persisted_rev:
                    gap_subtopic_ids.append(int(st["id"]))
                    updated_subtopics.append(st)
                    new_subtopic_count += 1
                    emit("subtopic", run_id, node="gap_analyzer", subtopic=st)
                if persisted_rev:
                    emit("log", run_id, node="gap_analyzer",
                         message=f"outline revision: +{len(persisted_rev)} new "
                                 "angle(s) from retrieved content")

        # --- 2) one-shot citation snowballing (round 1 only) ---
        snowball_seed_ids: list[int] = []
        already_snowballed = bool(state.get("snowball_seed_ids"))
        if (
            snowball_on
            and snowball_top_k > 0
            and research_round == 1
            and not already_snowballed
        ):
            academic_kept = [s for s in ranked if _is_academic(s)]

            def _score(s: dict) -> float:
                try:
                    return float(s.get("final_score") or 0.0)
                except Exception:
                    return 0.0

            academic_kept.sort(key=_score, reverse=True)
            for s in academic_kept:
                sid = s.get("id")
                if not isinstance(sid, int):
                    continue
                # must have a resolvable academic identity
                cid = s.get("canonical_id") or ""
                has_doi = isinstance(cid, str) and cid.startswith("doi:")
                is_openalex = (s.get("provider") or "").lower().startswith("openalex")
                if not (has_doi or is_openalex):
                    continue
                snowball_seed_ids.append(sid)
                if len(snowball_seed_ids) >= snowball_top_k:
                    break

        needs_more = bool(gap_subtopic_ids or snowball_seed_ids)

        emit("log", run_id, node="gap_analyzer",
             message=(
                 f"Round {research_round + 1}: {new_subtopic_count} yeni alt-soru "
                 f"+ {len(snowball_seed_ids)} kaynak snowball "
                 f"({len(under_covered)} under-covered)."
             ),
             new_subtopics=new_subtopic_count,
             snowball_seeds=len(snowball_seed_ids),
             needs_more_research=needs_more)

        out: dict = {"needs_more_research": needs_more}
        if gap_subtopic_ids:
            out["gap_subtopic_ids"] = gap_subtopic_ids
            # surface the new sub-questions to downstream nodes (researcher/ranker)
            out["subtopics"] = subtopics + updated_subtopics
        if snowball_seed_ids:
            out["snowball_seed_ids"] = snowball_seed_ids
        return out
    except Exception as exc:  # defensive: any failure ends the loop cleanly
        try:
            emit("log", run_id, node="gap_analyzer",
                 message=f"gap_analyzer failed; finalizing: {exc}")
        except Exception:
            pass
        return {"needs_more_research": False}


async def _propose_followups(
    state: dict,
    under_covered: list[dict],
    counts: dict[Any, int],
    language: str,
    grades: dict[Any, str] | None = None,
) -> list[dict]:
    """Ask the moderator model for 1-3 specific follow-up sub-questions."""
    root_query = state.get("root_query", "")
    grades = grades or {}
    # show the model the weakest gaps (lowest kept-source count first)
    gaps = sorted(under_covered, key=lambda s: counts.get(s.get("id"), 0))[:5]

    def _grade_note(sid: Any) -> str:
        g = grades.get(sid)
        if g == "weak":
            return ", retrieval=off-topic"
        if g == "ambiguous":
            return ", retrieval=weak"
        return ""

    gap_lines = "\n".join(
        f"- (id={s.get('id')}, kept_sources={counts.get(s.get('id'), 0)}"
        f"{_grade_note(s.get('id'))}) "
        f"{truncate(str(s.get('question') or ''), 200)}"
        for s in gaps
    )
    system = (
        "You are the Moderator of a multi-agent deep-research system. Some "
        "sub-questions are UNDER-COVERED (too few quality sources were found). "
        "Propose more specific follow-up sub-questions that would close the "
        "biggest evidence gaps."
    )
    user = (
        f"ROOT QUESTION:\n{root_query}\n\n"
        f"UNDER-COVERED SUB-QUESTIONS:\n{gap_lines}\n\n"
        f"Propose between 1 and {_MAX_NEW_SUBTOPICS} NEW, narrower follow-up "
        "sub-questions that target these gaps (more specific phrasings, missing "
        "angles, or adjacent facets). Do NOT repeat the existing questions.\n\n"
        "Return ONLY JSON of the form:\n"
        '  {"queries":[{"question": str, "parent_id": int|null, '
        '"perspective": str}]}\n'
        f"- parent_id should reference one of the under-covered ids above when "
        "the follow-up is a refinement of it, else null.\n"
        f"- Reply in this LANGUAGE: {language}.\n"
        "- JSON only, no prose, no code fences."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = await chat_json("moderator", messages)
    except Exception:
        return []
    items = _coerce_followups(raw)
    valid_parents = {s.get("id") for s in under_covered}
    out: list[dict] = []
    for it in items[:_MAX_NEW_SUBTOPICS]:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or "").strip()
        if not q:
            continue
        parent_id = it.get("parent_id")
        if parent_id not in valid_parents:
            parent_id = None
        out.append({
            "question": truncate(q, 800),
            "parent_id": parent_id,
            "perspective": (str(it.get("perspective")).strip()
                            if it.get("perspective") else "gap follow-up"),
        })
    return out


def _coerce_followups(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("queries", "questions", "items", "subtopics", "followups"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        if "question" in raw:
            return [raw]
    return []


def _norm_q(text: str) -> str:
    """Lowercased alphanumeric signature of a question for cheap dedup."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


async def _propose_outline_revisions(
    state: dict,
    ranked: list[dict],
    existing_questions: set[str],
    language: str,
) -> list[dict]:
    """Dynamic outline revision: propose NET-NEW angles the SOURCES reveal.

    Distinct from ``_propose_followups`` (which refines UNDER-covered existing
    sub-questions): this reads a digest of what was actually retrieved and asks
    whether the corpus surfaces an important facet the planner's outline misses.
    Strictly additive and deduped against the current tree — redundancy/merge is
    only advised in the log, never destructively dropped, so the loop can't
    oscillate. Returns up to ``_MAX_OUTLINE_ADD`` new subtopic specs (parent_id
    None = top-level angle). ``[]`` on any failure.
    """
    root_query = state.get("root_query", "")
    # Digest of the strongest retrieved sources (title + abstract snippet).
    def _fs(s: dict) -> float:
        try:
            return float(s.get("final_score") or 0.0)
        except Exception:
            return 0.0

    top = sorted(ranked, key=_fs, reverse=True)[:12]
    if not top:
        return []
    digest = "\n".join(
        f"- {truncate(str(s.get('title') or ''), 120)}: "
        f"{truncate(str(s.get('abstract') or ''), 160)}"
        for s in top
    )
    system = (
        "You are the Moderator of a multi-agent deep-research system. You revise "
        "the research OUTLINE based on what the retrieval ACTUALLY surfaced — "
        "spotting important facets the original plan missed."
    )
    user = (
        f"RESEARCH GOAL:\n{root_query}\n\n"
        f"RETRIEVED SOURCES (digest):\n{digest}\n\n"
        f"Looking at what was retrieved, propose up to {_MAX_OUTLINE_ADD} IMPORTANT "
        "NEW sub-questions that these sources show are relevant to the goal "
        "but that a typical outline would have OVERLOOKED. Only add genuinely new "
        "angles — do NOT restate facets already obviously covered.\n\n"
        'Return ONLY JSON: {"add":[{"question": str, "perspective": str}]}.\n'
        f"- Reply in this LANGUAGE: {language}.\n"
        "- JSON only, no prose, no code fences. Empty add list is fine."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = await chat_json("moderator", messages)
    except Exception:
        return []
    items = raw.get("add") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or "").strip()
        if not q or _norm_q(q) in existing_questions:
            continue
        existing_questions.add(_norm_q(q))
        out.append({
            "question": truncate(q, 800),
            "parent_id": None,
            "perspective": (str(it.get("perspective")).strip()
                            if it.get("perspective") else "outline revision"),
        })
        if len(out) >= _MAX_OUTLINE_ADD:
            break
    return out


async def _persist_new_subtopics(
    project_id: int,
    existing: list[dict],
    new_nodes: list[dict],
) -> list[dict]:
    """Append the new follow-up subtopics, preserving existing rows/ids.

    Uses an append-only insert (``repositories.add_subtopics``) so that prior
    subtopic ids — and the sources / scores that reference them — stay stable
    across rounds. Falls back to a full ``replace_subtopics`` rebuild (existing
    rows re-seeded with ``temp_id=id``) only if the append path is unavailable.
    Returns ONLY the newly inserted subtopic dicts (with real ids), in the
    graph's subtopic shape.
    """
    existing_ids = {s.get("id") for s in existing}
    max_depth = 0
    for s in existing:
        try:
            max_depth = max(max_depth, int(s.get("depth") or 0))
        except Exception:
            pass
    base_ord = len(existing)

    specs: list[dict] = []
    for i, nn in enumerate(new_nodes):
        parent_id = nn.get("parent_id")
        parent_id = parent_id if parent_id in existing_ids else None
        depth = (max_depth + 1) if parent_id is not None else 0
        specs.append({
            "parent_id": parent_id,
            "question": nn.get("question"),
            "perspective": nn.get("perspective"),
            "rationale": "gap-driven follow-up",
            "depth": depth,
            "ord": base_ord + i,
            "approved": True,
        })

    # Preferred path: append-only insert keeps existing ids intact. The write
    # shares the WAL file with the LangGraph checkpointer; add_subtopics retries
    # transient "database is locked" collisions internally (db.run_in_tx), so a
    # follow-up round is not silently dropped.
    persisted = None
    add_fn = getattr(repositories, "add_subtopics", None)
    if callable(add_fn):
        try:
            persisted = await asyncio.to_thread(add_fn, project_id, specs)
        except Exception:
            persisted = None

    if persisted is None:
        # Fallback: full rebuild (re-seed existing rows so the tree survives).
        nodes: list[dict] = []
        for s in existing:
            nodes.append({
                "temp_id": s.get("id"),
                "parent_temp_id": s.get("parent_id"),
                "question": s.get("question"),
                "perspective": s.get("perspective"),
                "rationale": s.get("rationale"),
                "depth": int(s.get("depth") or 0),
                "ord": int(s.get("ord") or 0),
                "approved": bool(s.get("approved")),
            })
        new_temp_ids = set()
        for i, sp in enumerate(specs):
            temp_id = -(i + 1)
            new_temp_ids.add(temp_id)
            nodes.append({
                "temp_id": temp_id,
                "parent_temp_id": sp.get("parent_id"),
                "question": sp.get("question"),
                "perspective": sp.get("perspective"),
                "rationale": sp.get("rationale"),
                "depth": sp.get("depth", 0),
                "ord": sp.get("ord", 0),
                "approved": True,
            })
        try:
            rebuilt = await asyncio.to_thread(
                repositories.replace_subtopics, project_id, nodes
            )
        except Exception:
            return []
        persisted = [p for p in rebuilt if p.get("temp_id") in new_temp_ids]

    out: list[dict] = []
    for p in persisted:
        out.append({
            "id": p["id"],
            "parent_id": p.get("parent_id"),
            "question": p.get("question"),
            "perspective": p.get("perspective"),
            "rationale": p.get("rationale") or "gap-driven follow-up",
            "depth": int(p.get("depth", 0) or 0),
            "ord": int(p.get("ord", 0) or 0),
            "approved": True,
            "status": "pending",
        })
    return out
