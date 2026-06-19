"""
Researcher node — parallel retrieval per leaf subtopic.

For each leaf sub-question selected for THIS round it fans out across web +
academic providers, optionally expanding the query (bilingual/paraphrase),
dedups, caps to a budget, fetches full text for the top web hits, persists each
source, indexes them into the vector store, and marks the subtopic done.

Round awareness:
  * round 1   -> all approved leaf subtopics (the original behaviour).
  * round >1  -> only subtopics in ``gap_subtopic_ids`` not yet researched.

After researching, if snowballing is armed (``snowball_seed_ids``), it expands
the citation graph of those seed sources and folds the discovered works in too.

Candidates merge into state via the additive reducer. Every branch is
defensive: a failure degrades to fewer sources, never crashes the run.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from ...config import get_settings
from ...db import repositories
from ...llm.provider import chat_json
from ...retrieval import vector_store
from ...retrieval.dedup import dedup_candidates
from ...sources import fulltext, registry
from ...utils.http import fetch_text
from ...utils.text import detect_language, extract_main_text, truncate
from ..events import emit

_FULLTEXT_WEB_LIMIT = 6
_FULLTEXT_CHARS = 6000
_FULLTEXT_ACADEMIC_LIMIT = 4
_FULLTEXT_ACADEMIC_CHARS = 8000
_FULLTEXT_MIN_LEN = 400  # candidates with shorter full_text are eligible for enrichment


def _leaves(approved: list[dict]) -> list[dict]:
    """Approved subtopics that are not a parent of another approved subtopic."""
    ids = {s.get("id") for s in approved}
    parent_ids = {s.get("parent_id") for s in approved if s.get("parent_id") in ids}
    leaves = [s for s in approved if s.get("id") not in parent_ids]
    return leaves or approved


async def expand_queries(
    question: str,
    language: str,
    n: int,
    bilingual: bool,
    model_role: str = "moderator",
) -> list[str]:
    """Return [question] plus up to n-1 query variants.

    When ``bilingual`` is on, the variants include a translation into the OTHER
    language (tr<->en, detected from the question) plus a paraphrase. Implemented
    via a single chat_json call; on ANY failure returns just ``[question]``.
    Deduped and capped to ``n``.
    """
    base = (question or "").strip()
    if not base:
        return []
    try:
        n = int(n)
    except Exception:
        n = 1
    if n <= 1 or not bilingual:
        return [base]

    try:
        lang = language if language in ("tr", "en") else detect_language(base)
    except Exception:
        lang = "en"
    other = "en" if lang == "tr" else "tr"

    system = (
        "You expand a search sub-question into a few alternative search queries "
        "for a research engine. Keep them faithful to the original intent."
    )
    user = (
        f"ORIGINAL QUESTION (language={lang}):\n{base}\n\n"
        f"Produce up to {max(1, n - 1)} ALTERNATIVE search queries:\n"
        f"- exactly one faithful translation into '{other}',\n"
        "- one or more close paraphrases in the original language.\n\n"
        'Return ONLY JSON: {"queries": [str, ...]}. No prose, no code fences.'
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = await chat_json(model_role, messages)
    except Exception:
        return [base]

    variants: list[str] = []
    if isinstance(raw, dict):
        q = raw.get("queries")
        if isinstance(q, list):
            variants = [str(x).strip() for x in q if str(x or "").strip()]
    elif isinstance(raw, list):
        variants = [str(x).strip() for x in raw if str(x or "").strip()]

    # dedup (case-insensitive), keep original first, cap to n
    out: list[str] = [base]
    seen = {base.lower()}
    for v in variants:
        key = v.lower()
        if key and key not in seen:
            out.append(v)
            seen.add(key)
        if len(out) >= n:
            break
    return out[:n] or [base]


async def researcher(state: dict) -> dict:
    run_id = state["run_id"]
    language = state.get("language")
    research_round = int(state.get("research_round", 0) or 0) + 1
    emit("node_started", run_id, node="researcher",
         message=f"Retrieving sources (round {research_round})")

    settings = get_settings()
    results_per_source = int(state.get("results_per_source", settings.results_per_source))
    max_sources = int(state.get("max_sources_per_subtopic",
                                getattr(settings, "max_sources_per_subtopic", 25)))
    bilingual = bool(state.get("bilingual"))
    query_variants = int(state.get("query_variants", getattr(settings, "query_variants", 1)) or 1)

    subtopics = list(state.get("subtopics") or [])
    approved = [s for s in subtopics if s.get("approved")]
    if not approved:
        approved = subtopics
    leaves = _leaves(approved)

    # --- choose subtopics to research this round ---
    if research_round <= 1:
        to_research = leaves
    else:
        gap_ids = set(state.get("gap_subtopic_ids") or [])
        already = set(state.get("researched_subtopic_ids") or [])
        # match against the FULL subtopic set (new gap subtopics may not be leaves yet)
        pool = {s.get("id"): s for s in subtopics}
        to_research = [
            pool[sid] for sid in gap_ids
            if sid in pool and sid not in already
        ]

    researched_ids: list[int] = []

    async def research_one(st: dict) -> list[dict]:
        sid_topic = st.get("id")
        q = str(st.get("question") or "").strip()
        collected: list[dict] = []
        if not q:
            return collected

        # --- query expansion (feature d) ---
        queries = [q]
        if bilingual and query_variants > 1:
            try:
                queries = await expand_queries(
                    q, language or "auto", query_variants, bilingual
                )
            except Exception:
                queries = [q]
        if not queries:
            queries = [q]

        per_provider_limit = (
            max(4, results_per_source // len(queries)) if len(queries) > 1
            else results_per_source
        )

        # terminal-log: announce retrieval for this subtopic
        try:
            provs = registry.enabled_providers()
            n_prov = len(provs)
            names = ", ".join(p.name for p in provs[:5])
            suffix = f" ({names})" if names else ""
            emit("log", run_id, node="researcher",
                 message=f'search: "{q[:80]}" -> querying {n_prov} providers{suffix}')
        except Exception:
            pass

        try:
            if len(queries) == 1:
                cands = await registry.search_all(
                    queries[0],
                    kinds=("web", "academic"),
                    per_provider_limit=per_provider_limit,
                    language=language,
                )
            else:
                batches = await asyncio.gather(
                    *(
                        registry.search_all(
                            qq,
                            kinds=("web", "academic"),
                            per_provider_limit=per_provider_limit,
                            language=language,
                        )
                        for qq in queries
                    ),
                    return_exceptions=True,
                )
                cands = []
                for b in batches:
                    if isinstance(b, BaseException) or not b:
                        continue
                    cands.extend(b)
        except Exception as exc:
            return [{"__error__": f"researcher[{sid_topic}]: search_all failed: {exc}"}]

        try:
            cands = dedup_candidates(cands)
        except Exception:
            pass
        cands = cands[:max_sources]

        # Fetch full text for the first ~6 web candidates.
        web_done = 0
        for cand in cands:
            if web_done >= _FULLTEXT_WEB_LIMIT:
                break
            if getattr(cand, "kind", "web") != "web":
                continue
            url = getattr(cand, "url", None)
            if not url:
                continue
            web_done += 1
            emit("log", run_id, node="researcher", message=f"GET {url}")
            try:
                html = await fetch_text(url)
                if not html:
                    emit("log", run_id, node="researcher",
                         message=f"  skip/failed {url}")
                    continue
                txt = extract_main_text(html, url)
                if txt and len(txt) > 200:
                    cand.full_text = truncate(txt, _FULLTEXT_CHARS)
                    emit("log", run_id, node="researcher",
                         message=f"  ok ({len(txt)} chars) {url}")
                else:
                    emit("log", run_id, node="researcher",
                         message=f"  skip/failed {url}")
            except Exception:
                emit("log", run_id, node="researcher",
                     message=f"  skip/failed {url}")
                continue

        # Enrich OA full text for the top few academic/preprint candidates that
        # don't already have decent full text. Bounded + concurrent + time-safe.
        await _enrich_academic_fulltext(cands, run_id)

        collected = await _persist_candidates(run_id, cands, sid_topic)

        try:
            await vector_store.index_sources(run_id, collected)
        except Exception:
            pass

        try:
            await asyncio.to_thread(repositories.set_subtopic_status, sid_topic, "done")
        except Exception:
            pass

        if isinstance(sid_topic, int):
            researched_ids.append(sid_topic)

        return collected

    all_dicts: list[dict] = []
    errors: list[str] = []

    if to_research:
        gathered = await asyncio.gather(
            *(research_one(st) for st in to_research), return_exceptions=True
        )
        for res in gathered:
            if isinstance(res, BaseException):
                errors.append(f"researcher: branch failed: {res}")
                continue
            for d in res:
                if isinstance(d, dict) and "__error__" in d:
                    errors.append(d["__error__"])
                    continue
                all_dicts.append(d)

    # --- citation snowballing (feature c) ---
    seed_ids = list(state.get("snowball_seed_ids") or [])
    if state.get("snowball") and seed_ids:
        try:
            snow_dicts, snow_errs = await _snowball(run_id, seed_ids, subtopics)
            all_dicts.extend(snow_dicts)
            errors.extend(snow_errs)
        except Exception as exc:
            errors.append(f"researcher: snowball failed: {exc}")

    out: dict = {
        "candidates": all_dicts,
        "research_round": research_round,
        "researched_subtopic_ids": researched_ids,
        # consumed this round — clear so the loop bookkeeping stays clean
        "snowball_seed_ids": [],
        "gap_subtopic_ids": [],
    }
    if errors:
        out["errors"] = errors
    return out


async def _enrich_academic_fulltext(cands: list, run_id: int | None = None) -> None:
    """Best-effort OA full-text enrichment for the top academic candidates.

    Picks up to ``_FULLTEXT_ACADEMIC_LIMIT`` academic/preprint candidates that
    lack good full text, resolves OA full text concurrently, and writes it back
    onto ``cand.full_text``. Bounded and fully defensive: never raises, and a
    failure simply leaves the candidate's full_text unchanged.
    """
    targets = []
    for cand in cands:
        if getattr(cand, "kind", "web") not in ("academic", "preprint"):
            continue
        existing = getattr(cand, "full_text", None) or ""
        if len(existing) >= _FULLTEXT_MIN_LEN:
            continue
        targets.append(cand)
        if len(targets) >= _FULLTEXT_ACADEMIC_LIMIT:
            break
    if not targets:
        return

    async def _one(cand) -> None:
        try:
            d = dataclasses.asdict(cand)
        except Exception:
            return
        ident = d.get("doi") or d.get("url") or d.get("canonical_id") or "?"
        try:
            text = await fulltext.resolve_fulltext(d, max_chars=_FULLTEXT_ACADEMIC_CHARS)
        except Exception:
            text = None
        ok = bool(text and len(text) > 200)
        if run_id is not None:
            emit("log", run_id, node="researcher",
                 message=f"fulltext: {str(ident)[:80]} -> {'ok' if ok else 'none'}")
        if ok:
            try:
                cand.full_text = text
            except Exception:
                pass

    try:
        await asyncio.gather(*(_one(c) for c in targets), return_exceptions=True)
    except Exception:
        pass


async def _persist_candidates(run_id: int, cands: list, subtopic_id) -> list[dict]:
    """Upsert + stream + collect candidate dicts for indexing."""
    collected: list[dict] = []
    for cand in cands:
        try:
            d = dataclasses.asdict(cand)
        except Exception:
            continue
        d["subtopic_id"] = subtopic_id
        try:
            source_id = await asyncio.to_thread(repositories.upsert_source, run_id, d)
        except Exception:
            continue
        d["id"] = source_id
        emit("source_found", run_id, node="researcher",
             source={
                 "id": source_id,
                 "title": d.get("title"),
                 "url": d.get("url"),
                 "provider": d.get("provider"),
                 "kind": d.get("kind"),
                 "subtopic_id": subtopic_id,
             },
             subtopic_id=subtopic_id)
        emit("log", run_id, node="researcher",
             message=f"  + {d.get('provider') or '?'}: {str(d.get('title') or '(untitled)')[:80]}")
        collected.append(d)
    return collected


async def _snowball(run_id: int, seed_ids: list[int], subtopics: list[dict]):
    """Expand citations of the seed sources and persist the discovered works."""
    from ...sources import snowball  # local import keeps researcher import-light

    errors: list[str] = []

    # load seed source rows
    seeds: list[dict] = []
    for sid in seed_ids:
        try:
            row = await asyncio.to_thread(repositories.get_source, int(sid))
        except Exception:
            row = None
        if isinstance(row, dict):
            seeds.append(row)
    if not seeds:
        return [], errors

    emit("log", run_id, node="researcher",
         message=f"snowball: expanding citations from {len(seeds)} seed sources")

    try:
        new_cands = await snowball.expand_citations(seeds)
    except Exception as exc:
        return [], [f"researcher: expand_citations failed: {exc}"]
    if not new_cands:
        return [], errors

    try:
        new_cands = dedup_candidates(new_cands)
    except Exception:
        pass

    # attach to the most-relevant subtopic (root / first leaf) or None
    target_subtopic = None
    if subtopics:
        roots = [s for s in subtopics if s.get("parent_id") is None]
        target_subtopic = (roots[0] if roots else subtopics[0]).get("id")

    collected = await _persist_candidates(run_id, new_cands, target_subtopic)
    try:
        await vector_store.index_sources(run_id, collected)
    except Exception:
        pass

    if collected:
        emit("log", run_id, node="researcher",
             message=f"Snowball: {len(collected)} atıf kaynağı eklendi.",
             count=len(collected))
    return collected, errors
