"""
Verifier node — adversarial citation check (liveness + claim entailment).

Two independent verdicts per citation, kept distinct:

  * LIVENESS (`verified` / `dead_link`): DOI-backed canonical ids are treated as
    alive; otherwise the URL is liveness-checked. A claim whose citations are ALL
    dead is marked unsupported and, under the iteration cap, loops back to the
    synthesizer.
  * ENTAILMENT (`support` / `support_score`): does the cited source's text
    actually back the claim? A hybrid pass — an embedding prefilter picks the
    best-matching passage in the source (and short-circuits clearly off-topic
    citations), then an LLM judges supported / partial / unsupported and pulls a
    supporting quote. Sources with no stored text are honestly 'unverifiable'.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any, Optional

from ...config import get_settings
from ...db import repositories
from ...embeddings import embedder
from ...llm.provider import chat_json
from ...utils.http import check_url_alive
from ..events import emit

_MAX_CITATIONS = 30
# Below this claim<->best-passage cosine, the source plainly does not address the
# claim — mark unsupported without spending an LLM call (the prefilter half of
# the hybrid). Only applied when a real embedding similarity was available.
_LOW_SIM = 0.15
_MAX_PASSAGES = 12
_PASSAGE_CHARS = 600
_QUOTE_CHARS = 280
# Cap how many under-supported subtopics one verifier pass sends back for
# re-research, so a weak report can't fan out an unbounded extra round.
_MAX_RERESEARCH = 3

# How supportive each entailment verdict is (higher = better backs the claim).
# A claim's grounding = the BEST verdict across its citations: it is "grounded"
# when at least one source supports or partly supports it.
_SUPPORTIVENESS = {"supported": 3, "partial": 2, "unverifiable": 1, "unsupported": 0}
_GROUNDED_VERDICTS = {"supported", "partial"}


def _claim_grounding(claim_support: dict[Any, list[str]]) -> tuple[dict[str, int], Optional[float]]:
    """Reduce per-claim citation verdicts into a grounding breakdown.

    `claim_support` maps claim id -> the entailment verdicts of its citations.
    Each claim is scored by its BEST (most supportive) verdict. Returns
    (breakdown, grounded_share) where breakdown counts claims per best-verdict
    plus `graded`/`grounded` totals, and grounded_share = grounded / graded
    (None when no claim had a checkable verdict).
    """
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "unverifiable": 0}
    graded = 0
    grounded = 0
    for verdicts in claim_support.values():
        ranked = [v for v in verdicts if v in _SUPPORTIVENESS]
        if not ranked:
            continue
        best = max(ranked, key=lambda v: _SUPPORTIVENESS[v])
        counts[best] += 1
        graded += 1
        if best in _GROUNDED_VERDICTS:
            grounded += 1
    if graded == 0:
        return {**counts, "graded": 0, "grounded": 0, "share": 0.0}, None
    share = round(grounded / graded, 4)
    return {**counts, "graded": graded, "grounded": grounded, "share": share}, share


def _passages(text: str, *, max_passages: int = _MAX_PASSAGES) -> list[str]:
    """Split source text into modest passages (paragraphs, long ones windowed)."""
    text = (text or "").strip()
    if not text:
        return []
    out: list[str] = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= _PASSAGE_CHARS:
            out.append(para)
        else:
            cur = ""
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if len(cur) + len(sent) + 1 <= _PASSAGE_CHARS:
                    cur = f"{cur} {sent}".strip()
                else:
                    if cur:
                        out.append(cur)
                    cur = sent
            if cur:
                out.append(cur)
        if len(out) >= max_passages:
            break
    return out[:max_passages]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


_WORD = re.compile(r"\w+", re.UNICODE)


def _lexical_overlap(claim: str, passage: str) -> float:
    """Jaccard overlap of word sets — the embedding-free fallback ranker."""
    a = {w.lower() for w in _WORD.findall(claim) if len(w) >= 3}
    b = {w.lower() for w in _WORD.findall(passage) if len(w) >= 3}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def _rank_passage(
    claim: str,
    passages: list[str],
    *,
    claim_vec: Optional[list[float]],
    passage_vecs: Optional[list[list[float]]],
) -> tuple[str, float, bool]:
    """Pick the passage most likely to back the claim.

    Returns (best_passage, score, used_embeddings). When embeddings are present
    the score is cosine similarity (gateable); otherwise it is a lexical-overlap
    fallback (not gateable — lexical alone is too noisy to declare unsupported).
    """
    if claim_vec and passage_vecs and len(passage_vecs) == len(passages):
        # A zero-norm (degenerate) claim embedding would make every cosine 0.0
        # and falsely trip the low-similarity prefilter; treat it as no-embedding
        # and fall back to lexical instead.
        cnorm = math.sqrt(sum(x * x for x in claim_vec))
        if cnorm > 0.0:
            sims = [_cosine(claim_vec, pv) for pv in passage_vecs]
            best_i = max(range(len(sims)), key=lambda i: sims[i])
            return passages[best_i], float(sims[best_i]), True
    # lexical fallback
    scores = [_lexical_overlap(claim, p) for p in passages]
    best_i = max(range(len(scores)), key=lambda i: scores[i]) if scores else 0
    return passages[best_i], float(scores[best_i]) if scores else 0.0, False


async def _entail(claim: str, passage: str) -> tuple[str, str]:
    """LLM judgement: does `passage` support `claim`? Returns (verdict, quote)."""
    system = (
        "You judge whether a SOURCE PASSAGE supports a CLAIM. Decide ONLY from "
        "the passage, never from outside knowledge. Output strict JSON only."
    )
    user = (
        f"CLAIM:\n{claim}\n\nSOURCE PASSAGE:\n{passage}\n\n"
        'Return JSON: {"verdict": "supported"|"partial"|"unsupported", '
        '"quote": "<short verbatim quote from the passage that backs the claim, '
        'or empty string>"}\n'
        "- supported: the passage clearly states or directly implies the claim.\n"
        "- partial: the passage is related and partly backs it, but not fully.\n"
        "- unsupported: the passage does not back the claim, or contradicts it."
    )
    try:
        raw = await chat_json("verifier", [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
    except Exception:
        raw = None
    obj: Any = raw
    if isinstance(raw, list):
        obj = next((x for x in raw if isinstance(x, dict)), {})
    if not isinstance(obj, dict):
        # Unparseable: we know the passage was on-topic (it passed the prefilter)
        # but cannot confirm entailment — 'partial' is the honest middle verdict.
        return "partial", ""
    verdict = str(obj.get("verdict") or "").strip().lower()
    if verdict not in ("supported", "partial", "unsupported"):
        verdict = "partial"
    quote = obj.get("quote")
    quote = quote.strip() if isinstance(quote, str) else ""
    return verdict, quote


async def _verify_support(
    claim_text: str,
    source: Optional[dict],
    *,
    claim_vec: Optional[list[float]],
    passages: list[str],
    passage_vecs: list[list[float]],
) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """Entailment verdict for one (claim, source) pair.

    Returns (support, support_score, quote). support is None only when the check
    could not run at all (caller leaves any prior value untouched).
    """
    if not claim_text:
        return None, None, None
    if not passages:
        # No stored source text to check against — be honest, do not guess.
        return "unverifiable", None, None

    best_passage, score, used_emb = await _rank_passage(
        claim_text, passages, claim_vec=claim_vec, passage_vecs=passage_vecs,
    )
    support_score = round(float(score), 4)
    if used_emb and score < _LOW_SIM:
        # Prefilter rejects: clearly off-topic, no LLM needed.
        return "unsupported", support_score, ""
    verdict, quote = await _entail(claim_text, best_passage)
    return verdict, support_score, (quote or best_passage)[:_QUOTE_CHARS]


async def verifier(state: dict) -> dict:
    run_id = state["run_id"]
    emit("node_started", run_id, node="verifier", message="Verifying citations")

    iteration = int(state.get("verifier_iteration", 0))
    settings = get_settings()
    max_iters = int(getattr(settings, "verifier_max_iterations", 2))

    errors: list[str] = []
    notes: list[dict] = []

    try:
        claims = await asyncio.to_thread(repositories.get_claims, run_id)
    except Exception as exc:
        errors.append(f"verifier: get_claims failed: {exc}")
        claims = []

    # Verdict per citation id, bounded to the first ~30 citations overall.
    verdicts: dict[int, bool] = {}
    # Entailment verdicts gathered per claim (for the grounding breakdown) and
    # each claim's subtopic (for entailment-driven re-research targeting).
    claim_support: dict[Any, list[str]] = {}
    claim_subtopic: dict[Any, Any] = {}
    checked = 0
    source_cache: dict[Any, dict] = {}
    # Cache the expensive embedding work: passage vectors per source, claim
    # vectors per claim (a source/claim can be cited more than once).
    passage_cache: dict[Any, tuple[list[str], list[list[float]]]] = {}
    claim_vec_cache: dict[Any, list[float]] = {}

    for cl in claims:
        claim_text = str(cl.get("text") or "").strip()
        for cit in cl.get("citations") or []:
            if checked >= _MAX_CITATIONS:
                break
            checked += 1
            citation_id = cit.get("id")
            source_id = cit.get("source_id")
            stance = cit.get("stance", "supporting")

            source = source_cache.get(source_id)
            if source is None and source_id is not None:
                try:
                    source = await asyncio.to_thread(repositories.get_source, source_id)
                except Exception:
                    source = None
                source_cache[source_id] = source or {}

            # --- liveness (link alive?) ---
            alive = False
            try:
                canonical = (source or {}).get("canonical_id") or ""
                url = (source or {}).get("url")
                if canonical.startswith("doi:"):
                    alive = True
                    emit("log", run_id, node="verifier",
                         message=f"verify {canonical} -> 200 (doi)")
                elif url:
                    alive, _code = await check_url_alive(url)
                    emit("log", run_id, node="verifier",
                         message=f"verify {url} -> {_code if alive else 'dead'}")
                else:
                    alive = False
            except Exception as exc:
                errors.append(f"verifier: check failed for source {source_id}: {exc}")
                alive = False

            # --- entailment (does the source back the claim?) ---
            support: Optional[str] = None
            support_score: Optional[float] = None
            quote: Optional[str] = None
            try:
                if claim_text and source_id is not None:
                    cached = passage_cache.get(source_id)
                    if cached is None:
                        text = (source or {}).get("full_text") or (source or {}).get("abstract") or ""
                        passages = _passages(text)
                        pvecs: list[list[float]] = []
                        if passages:
                            try:
                                pvecs = await embedder.aembed_texts(passages)
                            except Exception:
                                pvecs = []
                        cached = (passages, pvecs)
                        passage_cache[source_id] = cached
                    passages, pvecs = cached

                    claim_id = cl.get("id")
                    claim_vec = claim_vec_cache.get(claim_id) if claim_id is not None else None
                    if claim_vec is None and passages:
                        try:
                            claim_vec = await embedder.aembed_query(claim_text)
                        except Exception:
                            claim_vec = None
                        # Cache ONLY a successful, non-empty vector (and only for a
                        # real claim id). A transient embed failure is left uncached
                        # so it retries on the next source instead of permanently
                        # disabling the prefilter for this claim, and a None id can
                        # never collide other claims onto one cache entry.
                        if claim_vec and claim_id is not None:
                            claim_vec_cache[claim_id] = claim_vec

                    support, support_score, quote = await _verify_support(
                        claim_text, source,
                        claim_vec=claim_vec, passages=passages, passage_vecs=pvecs,
                    )
                    if support:
                        emit("log", run_id, node="verifier",
                             message=f"entail claim->source {source_id}: {support}"
                                     + (f" ({support_score:.2f})" if support_score is not None else ""))
            except Exception as exc:
                errors.append(f"verifier: entailment failed for source {source_id}: {exc}")

            if citation_id is not None:
                verdicts[citation_id] = alive
                try:
                    await asyncio.to_thread(
                        repositories.update_citation_verdict, citation_id,
                        verified=alive, dead_link=not alive,
                        support=support, support_score=support_score, quote=quote or None,
                    )
                except Exception:
                    pass

            # Record the entailment verdict against its claim for the grounding
            # breakdown and re-research targeting (the claim's subtopic is what
            # would be re-researched if its sources don't back it).
            if support:
                claim_key = cl.get("id")
                claim_support.setdefault(claim_key, []).append(support)
                claim_subtopic.setdefault(claim_key, cl.get("subtopic_id"))

            emit("citation_verified", run_id, node="verifier",
                 source_id=source_id, verified=alive, dead_link=not alive, stance=stance,
                 support=support, support_score=support_score)
        if checked >= _MAX_CITATIONS:
            break

    # A claim is fatal if it HAS citations and ALL of them are dead (liveness).
    fatal_bool = False
    for cl in claims:
        cits = cl.get("citations") or []
        checked_cits = [c for c in cits if c.get("id") in verdicts]
        if not checked_cits:
            continue
        if all(verdicts.get(c.get("id")) is False for c in checked_cits):
            fatal_bool = True
            try:
                await asyncio.to_thread(repositories.set_claim_status, cl["id"], "unsupported")
            except Exception:
                pass
            notes.append({"claim_id": cl.get("id"), "issue": "all_citations_dead",
                          "text": cl.get("text", "")[:200]})

    verifier_fatal = bool(fatal_bool and iteration < max_iters)

    # --- fold entailment back into the report: grounding-weighted certainty ---
    # The synthesizer saved `certainty` as the avg retrieval SCORE of cited
    # sources — which says nothing about whether those sources actually back the
    # claims. Rewrite it to the share of claims whose cited source text entails
    # them (the verdicts we just computed), and persist the per-verdict breakdown
    # so the report can show how well-grounded it is, not just how well-retrieved.
    grounding, grounded_share = _claim_grounding(claim_support)
    if grounded_share is not None:
        try:
            await asyncio.to_thread(
                repositories.update_report_grounding, run_id, grounded_share, grounding
            )
        except Exception as exc:
            errors.append(f"verifier: grounding persist failed: {exc}")
        emit("report_grounding", run_id, node="verifier",
             certainty=grounded_share, grounding=grounding)
        emit("log", run_id, node="verifier",
             message=f"grounding: {grounding['grounded']}/{grounding['graded']} claims "
                     f"backed by sources ({int(grounded_share * 100)}%)")

    # --- entailment-driven re-research ---
    # A claim whose citations ALL came back 'unsupported' (the source text
    # actively fails to back it — not merely 'unverifiable') is the strongest
    # signal the report is asserting something its evidence doesn't support.
    # Route that claim's subtopic back to the researcher to find evidence that
    # actually backs (or refutes) it. Bounded hard: at most ``_MAX_RERESEARCH``
    # subtopics per pass, each re-researched at most once across the run, and
    # only while under the verifier iteration cap.
    already_reresearched = set(state.get("reresearched_subtopic_ids") or [])
    reresearch: list[int] = []
    for claim_key, verdicts_list in claim_support.items():
        ranked = [v for v in verdicts_list if v in _SUPPORTIVENESS]
        if not ranked:
            continue
        best = max(ranked, key=lambda v: _SUPPORTIVENESS[v])
        if best != "unsupported":
            continue
        sid = claim_subtopic.get(claim_key)
        if not isinstance(sid, int) or sid in already_reresearched or sid in reresearch:
            continue
        reresearch.append(sid)
        notes.append({"claim_id": claim_key, "issue": "sources_do_not_support",
                      "subtopic_id": sid})
        if len(reresearch) >= _MAX_RERESEARCH:
            break

    needs_evidence = bool(reresearch and not verifier_fatal and iteration < max_iters)

    out: dict = {
        "verifier_iteration": iteration + 1,
        "verifier_fatal": verifier_fatal,
        "verifier_needs_evidence": needs_evidence,
        "verifier_notes": notes,
    }
    if needs_evidence:
        out["reresearch_subtopic_ids"] = reresearch
        # Mark them retried NOW so the next verifier pass can't pick them again
        # even if re-research fails to find supporting evidence (no oscillation).
        out["reresearched_subtopic_ids"] = reresearch
        emit("log", run_id, node="verifier",
             message=f"re-research: {len(reresearch)} subtopic(s) whose sources "
                     "do not support their claims")
    if errors:
        out["errors"] = errors
    return out
