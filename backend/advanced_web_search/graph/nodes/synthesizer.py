"""
Synthesizer node — grounded report generation + claim extraction.

Builds a numbered source list from the kept sources, grounds each sub-question
via hybrid retrieval, then streams a comprehensive cited markdown report. A
second structured pass extracts claims and their [n]->source citations, which
are persisted. Comprehensiveness and certainty metrics are computed and the
report is saved.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from ...config import (
    DEFAULT_REPORT_LANGUAGE,
    REPORT_LANGUAGE_NAMES,
    depth_preset,
    language_name,
    sanitize_report_languages,
)
from ...db import repositories
from ...llm.provider import chat, chat_json, chat_stream
from ...retrieval import vector_store
from ...utils.text import detect_language
from ..events import emit


def _report_token_budget(state: dict) -> int:
    """Max output tokens for the streamed report.

    A persisted ``report_max_tokens`` setting wins (clamped to a sane range);
    otherwise the active depth preset decides. The preset ceiling (8000) stays
    within the output cap of EVERY default cloud provider — DeepSeek's 8192 is
    the lowest — so a long report never trips a provider 400. See
    config.DEPTH_PRESETS.
    """
    try:
        override = repositories.get_setting("report_max_tokens")
    except Exception:
        override = None
    if override is not None:
        try:
            # Clamp both ends: a floor keeps a report usable; an upper bound
            # stops an operator-set value from exceeding a model's output cap
            # and 400-ing through both the stream and its non-stream fallback.
            return max(512, min(int(override), 64000))
        except (TypeError, ValueError):
            pass
    preset = depth_preset(state.get("depth"))
    return int(preset.get("report_max_tokens", 8000))


def _resolve_languages(state: dict) -> list[str]:
    """Resolve report languages to CONCRETE codes, primary first.

    Reads state['report_languages'] (may contain 'auto'); falls back to the
    single 'language' field for older runs; resolves 'auto' via the detected
    language of the root query; drops unknowns; dedups preserving order."""
    raw = state.get("report_languages") or [state.get("language") or "auto"]
    codes = sanitize_report_languages(raw)
    query = state.get("root_query") or ""
    resolved: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code == "auto":
            try:
                det = detect_language(query)
            except Exception:
                det = "auto"
            code = det if det in REPORT_LANGUAGE_NAMES else DEFAULT_REPORT_LANGUAGE
        if code not in REPORT_LANGUAGE_NAMES:
            code = DEFAULT_REPORT_LANGUAGE
        if code not in seen:
            resolved.append(code)
            seen.add(code)
    return resolved or [DEFAULT_REPORT_LANGUAGE]


async def synthesizer(state: dict) -> dict:
    run_id = state["run_id"]
    root_query = state.get("root_query", "")
    extra_instructions = state.get("extra_instructions", "") or ""
    emit("node_started", run_id, node="synthesizer", message="Writing the report")
    emit("log", run_id, node="synthesizer", message="synthesizing report...")

    errors: list[str] = []

    ranked = list(state.get("ranked_sources") or [])
    subtopics = list(state.get("subtopics") or [])
    approved = [s for s in subtopics if s.get("approved")] or subtopics

    # --- numbered source list: assign [n] indices ---
    # n (1-based) -> source dict ; and source_id -> n
    numbered: list[dict] = []
    n_of_source: dict[Any, int] = {}
    for s in ranked:
        sid = s.get("id")
        if sid is None:
            continue
        n = len(numbered) + 1
        numbered.append(s)
        n_of_source[sid] = n

    def _src_line(n: int, s: dict) -> str:
        title = s.get("title") or "(untitled)"
        url = s.get("url") or ""
        venue = s.get("venue") or s.get("provider") or ""
        date = s.get("published_date") or ""
        meta = " · ".join(x for x in (venue, date) if x)
        suffix = f" — {meta}" if meta else ""
        return f"[{n}] {title}{suffix} {url}".strip()

    source_block = "\n".join(_src_line(i + 1, s) for i, s in enumerate(numbered))

    # --- grounding via hybrid_search per approved subtopic ---
    referenced_ids: set[Any] = set()
    for st in approved:
        q = str(st.get("question") or "")
        if not q:
            continue
        try:
            hits = await vector_store.hybrid_search(q, run_id, top_k=8)
        except Exception:
            hits = []
        for h in hits or []:
            sid = h.get("source_id")
            if sid is not None:
                referenced_ids.add(sid)

    sub_lines = "\n".join(
        f"- {st.get('question')}" + (f" (perspective: {st.get('perspective')})"
                                      if st.get("perspective") else "")
        for st in approved if st.get("question")
    )

    instr_block = f"\n\nADDITIONAL USER INSTRUCTIONS:\n{extra_instructions}" if extra_instructions else ""

    system = (
        "You are the Synthesizer of a deep-research system. You write a "
        "COMPREHENSIVE, well-structured markdown report grounded ONLY in the "
        "provided numbered sources. Every factual claim MUST carry an inline "
        "citation marker like [1] or [2][5]. Do NOT make uncited claims. Cite "
        "only the numbered sources listed."
    )
    def _user_prompt(lang_code: str) -> str:
        lang = language_name(lang_code)
        return (
            f"ROOT QUESTION:\n{root_query}\n\n"
            f"SUB-QUESTIONS TO COVER:\n{sub_lines}\n\n"
            f"NUMBERED SOURCES (cite by their [n]):\n{source_block or '(no sources)'}\n\n"
            f"Write the ENTIRE report in {lang}. Use {lang} for ALL headings, prose "
            "and the Consensus section. Keep inline citation markers like [1], "
            "numbers, URLs and proper names unchanged.\n"
            "Structure it with markdown headings, address each sub-question, and "
            "synthesize across sources (do not just summarize each one). Mark every "
            "claim with inline [n] citations. End with a short '## Consensus' section "
            "(one paragraph) describing where the sources agree and disagree."
            f"{instr_block}"
        )

    # --- generate the report(s): primary streams, others run concurrently ---
    report_max_tokens = _report_token_budget(state)
    languages = _resolve_languages(state)
    primary = languages[0]
    emit("log", run_id, node="synthesizer",
         message=f"report languages: {', '.join(languages)}")

    async def _generate(lang: str, stream: bool) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": _user_prompt(lang)},
        ]
        text = ""
        if stream:
            try:
                async for tok in chat_stream("synthesizer", messages, max_tokens=report_max_tokens):
                    if not tok:
                        continue
                    text += tok
                    emit("token", run_id, node="synthesizer", text=tok, language=lang)
            except Exception as exc:
                errors.append(f"synthesizer[{lang}]: streaming failed: {exc}")
        else:
            emit("log", run_id, node="synthesizer",
                 message=f"writing {language_name(lang)} report in parallel…")
            try:
                text = await chat("synthesizer", messages, max_tokens=report_max_tokens)
            except Exception as exc:
                errors.append(f"synthesizer[{lang}]: generation failed: {exc}")
        return text or ""

    results = await asyncio.gather(
        _generate(primary, True),
        *[_generate(lang, False) for lang in languages[1:]],
    )
    markdown_by_lang: dict[str, str] = {}
    for lang, md in zip(languages, results):
        md = (md or "").strip() or f"# {root_query}\n\n_No report could be generated._"
        markdown_by_lang[lang] = md
    report_markdown = markdown_by_lang[primary]   # primary drives claims + return state

    # --- extract claims (structured) ---
    claims: list[dict] = []
    extract_system = (
        "You extract atomic factual claims and their citations from a research "
        "report. Output strict JSON only."
    )
    extract_user = (
        "From the report below, extract the key factual claims. Return ONLY a JSON "
        "array of objects:\n"
        '  {"text": str, "subtopic_id": int|null, '
        '"citations": [{"n": int, "stance": "supporting"|"contradicting"|"neutral"}]}\n'
        "where each n is a citation marker [n] used in the report. Use the sub-question "
        "ordering for subtopic_id only if obvious, else null.\n\n"
        f"SUB-QUESTIONS (in order):\n{sub_lines}\n\n"
        f"REPORT:\n{report_markdown[:12000]}"
    )
    try:
        raw = await chat_json("synthesizer", [
            {"role": "system", "content": extract_system},
            {"role": "user", "content": extract_user},
        ])
        claims = _coerce_list(raw)
    except Exception as exc:
        errors.append(f"synthesizer: claim extraction failed: {exc}")
        claims = []

    # map [n] -> source_id
    source_of_n: dict[int, Any] = {i + 1: s.get("id") for i, s in enumerate(numbered)}
    approved_ids = [st.get("id") for st in approved if st.get("id") is not None]

    persisted_claims: list[dict] = []
    cited_source_ids: set[Any] = set()
    for cl in claims:
        if not isinstance(cl, dict):
            continue
        text = str(cl.get("text") or "").strip()
        if not text:
            continue
        subtopic_id = cl.get("subtopic_id")
        if not (isinstance(subtopic_id, int) and subtopic_id in approved_ids):
            subtopic_id = None
        try:
            cid = await asyncio.to_thread(repositories.insert_claim, run_id, subtopic_id, text)
        except Exception:
            continue
        cl_citations: list[dict] = []
        for cit in (cl.get("citations") or []):
            if not isinstance(cit, dict):
                continue
            try:
                n = int(cit.get("n"))
            except Exception:
                continue
            src_id = source_of_n.get(n)
            if src_id is None:
                continue
            stance = cit.get("stance") or "supporting"
            if stance not in ("supporting", "contradicting", "neutral"):
                stance = "supporting"
            try:
                await asyncio.to_thread(
                    repositories.insert_citation, cid, src_id,
                    stance=stance, supporting_quote="",
                )
            except Exception:
                pass
            cited_source_ids.add(src_id)
            cl_citations.append({"n": n, "source_id": src_id, "stance": stance})
        persisted_claims.append({
            "id": cid, "text": text, "subtopic_id": subtopic_id,
            "citations": cl_citations,
        })

    # --- metrics ---
    # comprehensiveness = fraction of approved subtopics with >=1 kept source
    subtopics_with_sources: set[Any] = set()
    for s in ranked:
        if s.get("subtopic_id") is not None:
            subtopics_with_sources.add(s.get("subtopic_id"))
    n_approved = max(1, len(approved_ids))
    comprehensiveness = len([sid for sid in approved_ids
                             if sid in subtopics_with_sources]) / n_approved
    comprehensiveness = round(min(1.0, max(0.0, comprehensiveness)), 4)

    # certainty = avg final_score of cited sources (0..1)
    final_by_id: dict[Any, float] = {}
    for s in ranked:
        sid = s.get("id")
        if sid is not None:
            try:
                final_by_id[sid] = float(s.get("final_score") or 0.0)
            except Exception:
                final_by_id[sid] = 0.0
    cited_scores = [final_by_id[sid] for sid in cited_source_ids if sid in final_by_id]
    if not cited_scores:
        cited_scores = list(final_by_id.values())
    certainty = round(sum(cited_scores) / len(cited_scores), 4) if cited_scores else 0.0

    # The numbered source list (n == index+1) is what the LLM cited by [n];
    # persist it as the report's [n]->source-id mapping so the UI can resolve a
    # marker to the exact source and exports can number the bibliography to
    # match the body. Same for every language (the markers are kept unchanged).
    # `numbered` is already built skipping id-less sources, so this never holds a
    # None; the guard keeps that invariant explicit (a None would silently shift
    # every later marker by one once the list is densified downstream).
    ref_ids = [sid for s in numbered if (sid := s.get("id")) is not None]

    # --- save + emit one report per language (primary first; ord=0 = primary) ---
    primary_consensus = ""
    for i, lang in enumerate(languages):
        md = markdown_by_lang[lang]
        consensus = _extract_consensus(md)
        if i == 0:
            primary_consensus = consensus
        try:
            report_id = await asyncio.to_thread(
                repositories.save_report, run_id, md,
                language=lang, ord=i,
                consensus_summary=consensus,
                comprehensiveness=comprehensiveness, certainty=certainty,
                ref_ids=ref_ids,
            )
        except Exception as exc:
            errors.append(f"synthesizer: save_report[{lang}] failed: {exc}")
            report_id = None
        try:
            report_row = await asyncio.to_thread(repositories.get_report, run_id, lang)
        except Exception:
            report_row = None
        created_at = report_row.get("created_at") if report_row else None
        emit("report", run_id, node="synthesizer",
             report={"id": report_id, "run_id": run_id, "markdown": md,
                     "language": lang, "ord": i, "is_primary": i == 0,
                     "consensus_summary": consensus,
                     "comprehensiveness": comprehensiveness, "certainty": certainty,
                     "references": ref_ids,
                     "created_at": created_at})

    out: dict = {
        "report_markdown": report_markdown,
        "consensus_summary": primary_consensus,
        "comprehensiveness": comprehensiveness,
        "certainty": certainty,
        "claims": persisted_claims,
        "report_languages": languages,
    }
    if errors:
        out["errors"] = errors
    return out


def _extract_consensus(markdown: str) -> str:
    if not markdown:
        return ""
    lines = markdown.splitlines()
    # look for a heading containing 'consensus' and take the text after it
    for i, line in enumerate(lines):
        if line.strip().startswith("#") and "consensus" in line.lower():
            para: list[str] = []
            for nxt in lines[i + 1:]:
                if nxt.strip().startswith("#"):
                    break
                if nxt.strip():
                    para.append(nxt.strip())
            if para:
                return " ".join(para)
    # fallback: last non-empty paragraph
    paras = [p.strip() for p in markdown.split("\n\n") if p.strip()]
    return paras[-1] if paras else ""


def _coerce_list(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("claims", "items", "facts"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        if "text" in raw:
            return [raw]
        return []
    if isinstance(raw, str):
        try:
            return _coerce_list(json.loads(raw))
        except Exception:
            return []
    return []
