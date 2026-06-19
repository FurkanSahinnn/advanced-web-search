"""
Data-access layer. All SQL lives here; nodes/api never write raw SQL.

Functions are synchronous (sqlite3); async callers should wrap them with
`asyncio.to_thread(...)`. Writes go through `db.tx()` (serialized + committed).
Sources/authors JSON-encode list fields. Row dicts mirror the schemas DTOs
loosely (the API maps them into Pydantic models).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Optional

from .database import get_conn, run_in_tx, tx


def _row(r: sqlite3.Row | None) -> Optional[dict]:
    return dict(r) if r is not None else None


def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #

def create_project(title: str, root_query: str, language: str = "auto",
                   report_languages: Optional[list[str]] = None) -> int:
    rl = json.dumps(report_languages, ensure_ascii=False) if report_languages is not None else None
    with tx() as c:
        cur = c.execute(
            "INSERT INTO projects(title, root_query, language, report_languages) VALUES(?,?,?,?)",
            (title, root_query, language, rl),
        )
        return int(cur.lastrowid)


def get_project(project_id: int) -> Optional[dict]:
    return _row(get_conn().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())


def list_projects(limit: int = 100) -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall())


def set_project_status(project_id: int, status: str) -> None:
    with tx() as c:
        c.execute(
            "UPDATE projects SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, project_id),
        )


def delete_project(project_id: int) -> None:
    with tx() as c:
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

def create_run(project_id: int) -> dict:
    thread_id = uuid.uuid4().hex
    with tx() as c:
        cur = c.execute(
            "INSERT INTO runs(project_id, thread_id, status) VALUES(?,?, 'running')",
            (project_id, thread_id),
        )
        run_id = int(cur.lastrowid)
    return {"id": run_id, "project_id": project_id, "thread_id": thread_id, "status": "running"}


def get_run(run_id: int) -> Optional[dict]:
    return _row(get_conn().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def get_run_by_thread(thread_id: str) -> Optional[dict]:
    return _row(get_conn().execute("SELECT * FROM runs WHERE thread_id=?", (thread_id,)).fetchone())


def latest_run_for_project(project_id: int) -> Optional[dict]:
    return _row(get_conn().execute(
        "SELECT * FROM runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,)
    ).fetchone())


def set_run_status(run_id: int, status: str, error: Optional[str] = None) -> None:
    finished = status in ("done", "error", "cancelled")
    with tx() as c:
        c.execute(
            "UPDATE runs SET status=?, error=?, finished_at=CASE WHEN ? THEN datetime('now') ELSE finished_at END WHERE id=?",
            (status, error, finished, run_id),
        )


# --------------------------------------------------------------------------- #
# Subtopics
# --------------------------------------------------------------------------- #

def replace_subtopics(project_id: int, nodes: list[dict]) -> list[dict]:
    """Replace the project's decomposition with `nodes` (id field is reassigned).

    Each node: {temp_id, parent_temp_id, question, perspective, rationale, depth, ord}.
    Returns the inserted nodes with real ids and a temp_id->id map applied to parents.

    This DELETE-then-reinsert rebuild shares the WAL file with the LangGraph
    checkpointer, so it runs through ``run_in_tx`` which re-executes the whole
    transaction on a transient ``database is locked`` collision (a partial
    failure that left zero subtopics would derail the run).
    """
    def _do(c: sqlite3.Connection) -> list[dict]:
        c.execute("DELETE FROM subtopics WHERE project_id=?", (project_id,))
        id_map: dict[Any, int] = {}
        ordered = sorted(nodes, key=lambda n: (n.get("depth", 0), n.get("ord", 0)))
        out: list[dict] = []
        for n in ordered:
            parent_real = id_map.get(n.get("parent_temp_id")) if n.get("parent_temp_id") is not None else None
            cur = c.execute(
                """INSERT INTO subtopics(project_id, parent_id, question, perspective, rationale, depth, ord, approved, status)
                   VALUES(?,?,?,?,?,?,?,?, 'pending')""",
                (project_id, parent_real, n["question"], n.get("perspective"),
                 n.get("rationale"), n.get("depth", 0), n.get("ord", 0),
                 1 if n.get("approved") else 0),
            )
            real_id = int(cur.lastrowid)
            if n.get("temp_id") is not None:
                id_map[n["temp_id"]] = real_id
            out.append({**n, "id": real_id, "parent_id": parent_real})
        return out

    return run_in_tx(_do)


def add_subtopics(project_id: int, nodes: list[dict]) -> list[dict]:
    """Append NEW subtopics without disturbing existing rows/ids.

    Each node: {parent_id, question, perspective, rationale, depth, ord, approved}.
    `parent_id` (when given) must be an already-persisted subtopic id. Returns the
    inserted nodes with their freshly assigned real ids. Used by the iterative
    gap loop to add follow-up sub-questions mid-run while keeping prior subtopic
    ids (and the sources/scores that reference them) stable.

    Runs through ``run_in_tx`` so a transient WAL-writer collision with the
    checkpointer is retried rather than silently dropping a follow-up round.
    """
    def _do(c: sqlite3.Connection) -> list[dict]:
        out: list[dict] = []
        for n in nodes:
            cur = c.execute(
                """INSERT INTO subtopics(project_id, parent_id, question, perspective, rationale, depth, ord, approved, status)
                   VALUES(?,?,?,?,?,?,?,?, 'pending')""",
                (project_id, n.get("parent_id"), n["question"], n.get("perspective"),
                 n.get("rationale"), n.get("depth", 0), n.get("ord", 0),
                 1 if n.get("approved") else 0),
            )
            out.append({**n, "id": int(cur.lastrowid)})
        return out

    return run_in_tx(_do)


def get_subtopics(project_id: int) -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM subtopics WHERE project_id=? ORDER BY depth, ord, id", (project_id,)
    ).fetchall())


def set_subtopic_approval(project_id: int, approved_ids: set[int], deleted_ids: set[int]) -> None:
    with tx() as c:
        if deleted_ids:
            c.executemany("DELETE FROM subtopics WHERE id=? AND project_id=?",
                          [(i, project_id) for i in deleted_ids])
        c.execute("UPDATE subtopics SET approved=0 WHERE project_id=?", (project_id,))
        if approved_ids:
            c.executemany("UPDATE subtopics SET approved=1 WHERE id=? AND project_id=?",
                          [(i, project_id) for i in approved_ids])


def set_subtopic_status(subtopic_id: int, status: str) -> None:
    with tx() as c:
        c.execute("UPDATE subtopics SET status=? WHERE id=?", (status, subtopic_id))


# --------------------------------------------------------------------------- #
# Sources / chunks / scores
# --------------------------------------------------------------------------- #

def upsert_source(run_id: int, cand: dict) -> int:
    """Insert (or fetch existing) a source by (run_id, canonical_id). Returns source id."""
    authors = json.dumps(cand.get("authors") or [], ensure_ascii=False)
    raw = json.dumps(cand.get("raw") or {}, ensure_ascii=False)[:200_000]

    def _do(c: sqlite3.Connection) -> int:
        existing = c.execute(
            "SELECT id FROM sources WHERE run_id=? AND canonical_id=?",
            (run_id, cand["canonical_id"]),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = c.execute(
            """INSERT INTO sources(run_id, subtopic_id, canonical_id, kind, provider, title,
               authors, venue, published_date, url, pdf_url, abstract, full_text,
               cited_by_count, is_oa, raw)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, cand.get("subtopic_id"), cand["canonical_id"], cand.get("kind", "web"),
             cand.get("provider"), cand.get("title"), authors, cand.get("venue"),
             cand.get("published_date"), cand.get("url"), cand.get("pdf_url"),
             cand.get("abstract"), cand.get("full_text"), cand.get("cited_by_count"),
             1 if cand.get("is_oa") else 0, raw),
        )
        return int(cur.lastrowid)

    return run_in_tx(_do)


def set_source_fulltext(source_id: int, full_text: str) -> None:
    with tx() as c:
        c.execute("UPDATE sources SET full_text=? WHERE id=?", (full_text, source_id))


def add_chunks(source_id: int, texts: list[str]) -> list[int]:
    def _do(c: sqlite3.Connection) -> list[int]:
        ids: list[int] = []
        for i, t in enumerate(texts):
            cur = c.execute(
                "INSERT INTO chunks(source_id, ordinal, text) VALUES(?,?,?)", (source_id, i, t)
            )
            ids.append(int(cur.lastrowid))
        return ids

    return run_in_tx(_do)


def upsert_score(source_id: int, b: dict) -> None:
    def _do(c: sqlite3.Connection) -> None:
        c.execute(
            """INSERT INTO source_scores(source_id, relevance, authority, recency, citation_impact,
                 evidence, final_score, match_score, evidence_type, kept, why_kept, breakdown)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 relevance=excluded.relevance, authority=excluded.authority, recency=excluded.recency,
                 citation_impact=excluded.citation_impact, evidence=excluded.evidence,
                 final_score=excluded.final_score, match_score=excluded.match_score,
                 evidence_type=excluded.evidence_type, kept=excluded.kept,
                 why_kept=excluded.why_kept, breakdown=excluded.breakdown""",
            (source_id, b.get("relevance", 0), b.get("authority", 0), b.get("recency", 0),
             b.get("citation_impact", 0), b.get("evidence", 0), b.get("final_score", 0),
             int(b.get("match_score", 0)), b.get("evidence_type", "unknown"),
             1 if b.get("kept", True) else 0, b.get("why_kept", ""),
             json.dumps(b.get("detail") or {}, ensure_ascii=False)),
        )

    run_in_tx(_do)


def get_sources(run_id: int, kept_only: bool = False) -> list[dict]:
    sql = """SELECT s.*, sc.relevance, sc.authority, sc.recency, sc.citation_impact, sc.evidence,
                    sc.final_score, sc.match_score, sc.evidence_type, sc.kept, sc.why_kept, sc.breakdown
             FROM sources s LEFT JOIN source_scores sc ON sc.source_id = s.id
             WHERE s.run_id=?"""
    if kept_only:
        sql += " AND COALESCE(sc.kept,1)=1"
    sql += " ORDER BY COALESCE(sc.final_score,0) DESC"
    return _rows(get_conn().execute(sql, (run_id,)).fetchall())


def get_source(source_id: int) -> Optional[dict]:
    return _row(get_conn().execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


# --------------------------------------------------------------------------- #
# Claims / citations / report
# --------------------------------------------------------------------------- #

def insert_claim(run_id: int, subtopic_id: Optional[int], text: str, status: str = "supported") -> int:
    def _do(c: sqlite3.Connection) -> int:
        cur = c.execute(
            "INSERT INTO claims(run_id, subtopic_id, text, status) VALUES(?,?,?,?)",
            (run_id, subtopic_id, text, status),
        )
        return int(cur.lastrowid)

    return run_in_tx(_do)


def insert_citation(claim_id: int, source_id: int, *, stance: str = "supporting",
                    supporting_quote: Optional[str] = None, verified: bool = False,
                    dead_link: bool = False) -> int:
    def _do(c: sqlite3.Connection) -> int:
        cur = c.execute(
            """INSERT INTO citations(claim_id, source_id, stance, supporting_quote, verified, dead_link)
               VALUES(?,?,?,?,?,?)""",
            (claim_id, source_id, stance, supporting_quote, 1 if verified else 0, 1 if dead_link else 0),
        )
        return int(cur.lastrowid)

    return run_in_tx(_do)


def update_citation_verdict(citation_id: int, *, verified: bool, dead_link: bool,
                            stance: Optional[str] = None, quote: Optional[str] = None) -> None:
    with tx() as c:
        c.execute(
            """UPDATE citations SET verified=?, dead_link=?,
               stance=COALESCE(?, stance), supporting_quote=COALESCE(?, supporting_quote)
               WHERE id=?""",
            (1 if verified else 0, 1 if dead_link else 0, stance, quote, citation_id),
        )


def set_claim_status(claim_id: int, status: str) -> None:
    with tx() as c:
        c.execute("UPDATE claims SET status=? WHERE id=?", (status, claim_id))


def get_claims(run_id: int) -> list[dict]:
    claims = _rows(get_conn().execute(
        "SELECT * FROM claims WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall())
    for cl in claims:
        cl["citations"] = _rows(get_conn().execute(
            "SELECT * FROM citations WHERE claim_id=?", (cl["id"],)
        ).fetchall())
    return claims


def save_report(run_id: int, markdown: str, *, language: str = "en", ord: int = 0,
                consensus_summary: str = "", comprehensiveness: float = 0.0,
                certainty: float = 0.0, ref_ids: Optional[list[int]] = None) -> int:
    # `ref_ids` is the [n]->source-id mapping (n == index+1) persisted as JSON so
    # clients/exports can resolve inline citation markers exactly. None for older
    # callers/runs that didn't compute it.
    refs_json = json.dumps(ref_ids, ensure_ascii=False) if ref_ids is not None else None

    def _do(c: sqlite3.Connection) -> int:
        cur = c.execute(
            """INSERT INTO reports(run_id, markdown, language, ord, consensus_summary,
                                   comprehensiveness, certainty, ref_ids)
               VALUES(?,?,?,?,?,?,?,?)""",
            (run_id, markdown, language, ord, consensus_summary, comprehensiveness,
             certainty, refs_json),
        )
        return int(cur.lastrowid)

    return run_in_tx(_do)


def get_report(run_id: int, language: Optional[str] = None) -> Optional[dict]:
    """Latest report for a run. With ``language`` -> that language's latest row;
    without -> the primary report (lowest ``ord``, then newest)."""
    if language is not None:
        return _row(get_conn().execute(
            "SELECT * FROM reports WHERE run_id=? AND language=? ORDER BY id DESC LIMIT 1",
            (run_id, language),
        ).fetchone())
    return _row(get_conn().execute(
        "SELECT * FROM reports WHERE run_id=? ORDER BY ord ASC, id DESC LIMIT 1", (run_id,)
    ).fetchone())


def get_reports(run_id: int) -> list[dict]:
    """Latest report row per language for a run, primary-first (by ``ord``)."""
    return _rows(get_conn().execute(
        """SELECT r.* FROM reports r
           JOIN (SELECT language, MAX(id) AS mid FROM reports WHERE run_id=? GROUP BY language) m
             ON r.id = m.mid
           ORDER BY r.ord ASC, r.id ASC""",
        (run_id,),
    ).fetchall())


# --------------------------------------------------------------------------- #
# App settings (key-value JSON)
# --------------------------------------------------------------------------- #

def get_setting(key: str) -> Any:
    row = get_conn().execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except Exception:
        return None


def set_setting(key: str, value: Any) -> None:
    with tx() as c:
        c.execute(
            """INSERT INTO app_settings(key, value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, json.dumps(value, ensure_ascii=False)),
        )
