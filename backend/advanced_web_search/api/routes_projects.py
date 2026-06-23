"""Project CRUD + the aggregate project detail endpoint.

Also hosts the row -> DTO mappers (`source_out`, `claim_out`) and the
subtopic tree builder reused by other routers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from ..db import repositories
from ..models.schemas import (
    AskAnswerOut,
    CitationOut,
    ClaimOut,
    ProjectCreate,
    ProjectOut,
    ReportGrounding,
    ReportOut,
    ReportQuality,
    RunOut,
    RunQueryOut,
    ScoreBreakdown,
    SourceOut,
    SubtopicOut,
)

router = APIRouter(tags=["projects"])


# --------------------------------------------------------------------------- #
# Mappers (DB row dict -> DTO)
# --------------------------------------------------------------------------- #

def _parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def build_subtopic_tree(flat_rows: list[dict]) -> list[SubtopicOut]:
    """Build a nested SubtopicOut tree (by parent_id) from flat DB rows."""
    by_id: dict[Any, SubtopicOut] = {}
    order: list[Any] = []
    for r in flat_rows:
        node = SubtopicOut(
            id=int(r["id"]),
            parent_id=r.get("parent_id"),
            question=r.get("question") or "",
            perspective=r.get("perspective"),
            rationale=r.get("rationale"),
            depth=int(r.get("depth") or 0),
            ord=int(r.get("ord") or 0),
            approved=bool(r.get("approved")),
            status=r.get("status") or "pending",
            children=[],
        )
        by_id[node.id] = node
        order.append(node.id)

    roots: list[SubtopicOut] = []
    for nid in order:
        node = by_id[nid]
        pid = node.parent_id
        if pid is not None and pid in by_id:
            by_id[pid].children.append(node)
        else:
            roots.append(node)
    return roots


def source_out(row: dict) -> SourceOut:
    """Map a joined sources+source_scores row into a SourceOut.

    `authors` is stored as a JSON string; `breakdown` (the score detail) is
    stored as a JSON string in source_scores. A ScoreBreakdown is attached only
    when a final_score is present (i.e., the source has been scored).
    """
    authors = _parse_json(row.get("authors"), [])
    if not isinstance(authors, list):
        authors = []

    score: Optional[ScoreBreakdown] = None
    if row.get("final_score") is not None:
        detail = _parse_json(row.get("breakdown"), {})
        if not isinstance(detail, dict):
            detail = {}
        score = ScoreBreakdown(
            relevance=row.get("relevance") or 0.0,
            authority=row.get("authority") or 0.0,
            recency=row.get("recency") or 0.0,
            citation_impact=row.get("citation_impact") or 0.0,
            evidence=row.get("evidence") or 0.0,
            final_score=row.get("final_score") or 0.0,
            match_score=int(row.get("match_score") or 0),
            evidence_type=row.get("evidence_type") or "unknown",
            kept=bool(row.get("kept", 1)),
            why_kept=row.get("why_kept") or "",
            detail=detail,
        )

    return SourceOut(
        id=int(row["id"]),
        subtopic_id=row.get("subtopic_id"),
        canonical_id=row.get("canonical_id") or "",
        kind=row.get("kind") or "web",
        provider=row.get("provider"),
        title=row.get("title"),
        authors=authors,
        venue=row.get("venue"),
        published_date=row.get("published_date"),
        url=row.get("url"),
        pdf_url=row.get("pdf_url"),
        abstract=row.get("abstract"),
        cited_by_count=row.get("cited_by_count"),
        is_oa=bool(row.get("is_oa")),
        score=score,
    )


def claim_out(row: dict) -> ClaimOut:
    citations = []
    for c in row.get("citations") or []:
        citations.append(
            CitationOut(
                id=int(c["id"]),
                source_id=int(c["source_id"]),
                stance=c.get("stance") or "supporting",
                supporting_quote=c.get("supporting_quote"),
                verified=bool(c.get("verified")),
                dead_link=bool(c.get("dead_link")),
                support=c.get("support"),
                support_score=c.get("support_score"),
            )
        )
    return ClaimOut(
        id=int(row["id"]),
        subtopic_id=row.get("subtopic_id"),
        text=row.get("text") or "",
        status=row.get("status") or "supported",
        citations=citations,
    )


def report_out(row: dict) -> ReportOut:
    """Map a `reports` row into a ReportOut (shared with routes_sources).

    `language`/`ord` are columns added with the multi-language report feature;
    older rows (NULL) fall back to the historical single-language defaults.
    `ref_ids` (the [n]->source-id mapping) is parsed into `references`; older
    rows without it yield an empty list.
    """
    raw_refs = _parse_json(row.get("ref_ids"), [])
    references: list[int] = []
    if isinstance(raw_refs, list):
        for x in raw_refs:
            try:
                references.append(int(x))
            except (TypeError, ValueError):
                continue
    grounding: Optional[ReportGrounding] = None
    raw_g = _parse_json(row.get("grounding"), None)
    if isinstance(raw_g, dict):
        try:
            grounding = ReportGrounding(**raw_g)
        except Exception:
            grounding = None
    quality: Optional[ReportQuality] = None
    raw_q = _parse_json(row.get("quality"), None)
    if isinstance(raw_q, dict):
        try:
            quality = ReportQuality(**raw_q)
        except Exception:
            quality = None
    return ReportOut(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        markdown=row.get("markdown") or "",
        language=row.get("language") or "en",
        ord=int(row.get("ord") or 0),
        consensus_summary=row.get("consensus_summary"),
        disagreements=row.get("disagreements"),
        comprehensiveness=row.get("comprehensiveness"),
        certainty=row.get("certainty"),
        references=references,
        grounding=grounding,
        quality=quality,
        created_at=str(row.get("created_at") or ""),
    )


def _project_out(row: dict) -> ProjectOut:
    report_languages = _parse_json(row.get("report_languages"), None)
    if not isinstance(report_languages, list):
        fallback = row.get("language")
        report_languages = [fallback] if fallback else ["auto"]
    return ProjectOut(
        id=int(row["id"]),
        title=row.get("title") or "",
        root_query=row.get("root_query") or "",
        language=row.get("language") or "auto",
        report_languages=report_languages,
        status=row.get("status") or "new",
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def run_query_out(row: dict) -> RunQueryOut:
    return RunQueryOut(
        id=int(row["id"]),
        subtopic_id=row.get("subtopic_id"),
        round=int(row.get("round") or 1),
        query=row.get("query") or "",
        hits=int(row.get("hits") or 0),
        created_at=str(row.get("created_at") or "") or None,
    )


def ask_answer_out(row: dict) -> AskAnswerOut:
    raw_refs = _parse_json(row.get("ref_ids"), [])
    references: list[int] = []
    if isinstance(raw_refs, list):
        for x in raw_refs:
            try:
                references.append(int(x))
            except (TypeError, ValueError):
                continue
    return AskAnswerOut(
        id=int(row["id"]),
        question=row.get("question") or "",
        answer=row.get("answer") or "",
        references=references,
        grounded=bool(row.get("grounded", 1)),
        created_at=str(row.get("created_at") or "") or None,
    )


def _run_out(row: dict) -> RunOut:
    return RunOut(
        id=int(row["id"]),
        project_id=int(row["project_id"]),
        thread_id=row.get("thread_id") or "",
        status=row.get("status") or "running",
        error=row.get("error"),
        started_at=str(row.get("started_at") or ""),
        finished_at=row.get("finished_at"),
        tokens_in=int(row.get("tokens_in") or 0),
        tokens_out=int(row.get("tokens_out") or 0),
        cost_usd=float(row.get("cost_usd") or 0.0),
        llm_calls=int(row.get("llm_calls") or 0),
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/projects", response_model=list[ProjectOut])
async def list_projects_endpoint() -> list[ProjectOut]:
    rows = await asyncio.to_thread(repositories.list_projects)
    return [_project_out(r) for r in rows]


@router.post("/projects")
async def create_project_endpoint(body: ProjectCreate) -> dict:
    title = body.title or body.query.strip()[:80]
    pid = await asyncio.to_thread(
        repositories.create_project, title, body.query, body.language,
        body.report_languages,
    )

    if body.depth:
        await asyncio.to_thread(repositories.set_setting, "depth", body.depth)
        # The depth preset (chosen on Home) is now the SOLE control for these
        # breadth/loop knobs — their Settings sliders were removed. Clear any stale
        # saved overrides so an old value can't silently shadow the chosen preset
        # (e.g. picking "quick" must actually mean 1 round / 4 subtopics, not a
        # previously-saved 3 / 12).
        for _k in (
            "max_research_rounds", "gap_min_sources", "query_variants", "snowball_top_k",
            "max_subtopics", "results_per_source",
        ):
            await asyncio.to_thread(repositories.delete_setting, _k)
    if body.weights is not None:
        await asyncio.to_thread(repositories.set_setting, "weights", body.weights.model_dump())
    if body.require_approval is not None:
        await asyncio.to_thread(
            repositories.set_setting, "require_approval", bool(body.require_approval)
        )

    await asyncio.to_thread(repositories.set_project_status, pid, "planning")
    run = await asyncio.to_thread(repositories.create_run, pid)

    project_row = await asyncio.to_thread(repositories.get_project, pid)
    run_row = await asyncio.to_thread(repositories.get_run, run["id"]) or run

    return {
        "project": _project_out(project_row),
        "run": _run_out(run_row),
    }


@router.get("/projects/{pid}")
async def get_project_endpoint(pid: int) -> dict:
    project_row = await asyncio.to_thread(repositories.get_project, pid)
    if not project_row:
        raise HTTPException(status_code=404, detail="project not found")

    latest = await asyncio.to_thread(repositories.latest_run_for_project, pid)
    subtopic_rows = await asyncio.to_thread(repositories.get_subtopics, pid)
    subtopics = build_subtopic_tree(subtopic_rows)

    report: Optional[ReportOut] = None
    reports: list[ReportOut] = []
    sources: list[SourceOut] = []
    claims: list[ClaimOut] = []
    queries: list[RunQueryOut] = []
    asks: list[AskAnswerOut] = []

    if latest:
        run_id = latest["id"]
        report_rows, source_rows, claim_rows, query_rows, ask_rows = await asyncio.gather(
            asyncio.to_thread(repositories.get_reports, run_id),
            asyncio.to_thread(repositories.get_sources, run_id),
            asyncio.to_thread(repositories.get_claims, run_id),
            asyncio.to_thread(repositories.get_run_queries, run_id),
            asyncio.to_thread(repositories.get_run_asks, run_id),
        )
        reports = [report_out(r) for r in report_rows]
        report = reports[0] if reports else None
        sources = [source_out(r) for r in source_rows]
        claims = [claim_out(r) for r in claim_rows]
        queries = [run_query_out(r) for r in query_rows]
        asks = [ask_answer_out(r) for r in ask_rows]

    return {
        "project": _project_out(project_row),
        "latest_run": _run_out(latest) if latest else None,
        "subtopics": subtopics,
        "report": report,
        "reports": reports,
        "sources": sources,
        "claims": claims,
        "queries": queries,
        "asks": asks,
    }


@router.delete("/projects/{pid}")
async def delete_project_endpoint(pid: int) -> dict:
    await asyncio.to_thread(repositories.delete_project, pid)
    return {"ok": True}
