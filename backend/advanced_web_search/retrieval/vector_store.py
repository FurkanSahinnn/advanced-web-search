"""
Hybrid retrieval over indexed source chunks.

Indexing builds chunks per source (title + body), persists them via the
repositories layer (which also populates `chunks_fts` through triggers), and —
when sqlite-vec is available — embeds each chunk and writes a row into the
`vec_chunks` vec0 virtual table.

Search fuses two retrievers with Reciprocal Rank Fusion (RRF):
    * VECTOR  : KNN over `vec_chunks` (sqlite-vec MATCH), scoped to the run.
    * LEXICAL : BM25 over `chunks_fts`, scoped to the run.

If sqlite-vec is unavailable we degrade to lexical-only. Every public call is
defensive: on error we log and return a safe value (0 indexed / [] results).
All synchronous SQLite work runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..config import get_settings
from ..db import database as db
from ..db import repositories
from ..embeddings import embedder
from ..utils.text import chunk_text

log = logging.getLogger("advanced_web_search.vector_store")

# Keep alphanumerics / unicode word chars; everything else becomes a separator.
_FTS_TOKEN = re.compile(r"[^\w]+", re.UNICODE)


def _sanitize_fts(query: str, *, max_terms: int = 32) -> str:
    """Turn an arbitrary query into a safe FTS5 MATCH string.

    Strips quotes/parens/operators by keeping only word tokens, then joins them
    with OR. Returns "" when nothing usable remains (caller should skip lexical).
    """
    if not query:
        return ""
    tokens = [t for t in _FTS_TOKEN.split(query) if t]
    # drop pure-noise single chars, cap term count
    tokens = [t for t in tokens if len(t) >= 2][:max_terms]
    if not tokens:
        # fall back to any single tokens if the >=2 filter emptied it
        tokens = [t for t in _FTS_TOKEN.split(query) if t][:max_terms]
    if not tokens:
        return ""
    # quote each term to neutralize any residual FTS syntax, join with OR
    return " OR ".join(f'"{t}"' for t in tokens)


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #

def _index_sources_sync(run_id: int, sources: list[dict]) -> int:
    total = 0
    vec_ok = False
    try:
        vec_ok = db.vec_available()
    except Exception:
        vec_ok = False

    serialize = None
    if vec_ok:
        try:
            import sqlite_vec  # noqa: F401

            serialize = sqlite_vec.serialize_float32
        except Exception as exc:
            log.warning("sqlite_vec serialize unavailable; indexing lexical-only: %s", exc)
            vec_ok = False

    for src in sources or []:
        try:
            source_id = src.get("id")
            if source_id is None:
                continue
            title = (src.get("title") or "").strip()
            body = src.get("full_text") or src.get("abstract") or ""
            text = f"{title}\n{body}".strip() if title else (body or "").strip()
            chunks = chunk_text(text)
            if not chunks:
                continue

            chunk_ids = repositories.add_chunks(int(source_id), chunks)
            total += len(chunk_ids)
        except Exception as exc:
            log.warning("indexing source %s failed: %s", src.get("id"), exc)
            continue

        # vector rows (best-effort, isolated from lexical success)
        if not vec_ok or serialize is None:
            continue
        try:
            vectors = None
            # aembed in a sync context: drive a private event loop-free path
            vectors = _embed_sync(chunks)
            if not vectors or len(vectors) != len(chunk_ids):
                continue
            with db.tx() as conn:
                for cid, vec in zip(chunk_ids, vectors):
                    conn.execute(
                        "INSERT INTO vec_chunks(chunk_id, source_id, embedding) VALUES(?,?,?)",
                        (int(cid), int(source_id), serialize([float(x) for x in vec])),
                    )
        except Exception as exc:
            log.warning("vector indexing for source %s failed: %s", source_id, exc)
            continue

    return total


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Synchronous embedding (used inside the to_thread worker)."""
    try:
        return embedder.embed_texts(texts)
    except Exception as exc:
        log.warning("embed_texts failed: %s", exc)
        return []


async def index_sources(run_id: int, sources: list[dict]) -> int:
    """Chunk + persist + (optionally) vector-index each source. Returns chunk count."""
    try:
        return await asyncio.to_thread(_index_sources_sync, run_id, sources)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("index_sources failed: %s", exc)
        return 0


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

def _vector_search_sync(qvec: list[float], run_id: int, k: int) -> list[int]:
    """Return chunk_ids ranked best->worst from the vec KNN, scoped to run_id."""
    try:
        import sqlite_vec
    except Exception:
        return []
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT chunk_id, source_id, distance FROM vec_chunks "
            "WHERE embedding MATCH ? AND k = ?",
            (sqlite_vec.serialize_float32([float(x) for x in qvec]), int(k)),
        ).fetchall()
    except Exception as exc:
        log.warning("vector KNN failed: %s", exc)
        return []

    if not rows:
        return []

    # keep only chunks whose source belongs to this run
    try:
        source_ids = {int(r["source_id"]) for r in rows}
        placeholders = ",".join("?" for _ in source_ids)
        valid = {
            int(r["id"])
            for r in conn.execute(
                f"SELECT id FROM sources WHERE run_id=? AND id IN ({placeholders})",
                (run_id, *source_ids),
            ).fetchall()
        }
    except Exception as exc:
        log.warning("vector run-scope filter failed: %s", exc)
        return []

    ranked: list[int] = []
    # rows already ordered by distance asc (closest first) from sqlite-vec
    for r in rows:
        if int(r["source_id"]) in valid:
            ranked.append(int(r["chunk_id"]))
    return ranked


def _lexical_search_sync(match: str, run_id: int, limit: int) -> list[int]:
    """Return chunk_ids ranked best->worst from BM25, scoped to run_id."""
    if not match:
        return []
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT c.id AS chunk_id, c.source_id AS source_id, bm25(chunks_fts) AS rank "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            "JOIN sources s ON s.id = c.source_id "
            "WHERE chunks_fts MATCH ? AND s.run_id = ? ORDER BY rank LIMIT ?",
            (match, run_id, int(limit)),
        ).fetchall()
    except Exception as exc:
        log.warning("lexical search failed: %s", exc)
        return []
    # bm25 lower = better, query already ORDER BY rank ASC
    return [int(r["chunk_id"]) for r in rows]


def _fetch_chunk_rows(chunk_ids: list[int]) -> dict[int, dict]:
    """Map chunk_id -> {text, source_id} for the given ids."""
    if not chunk_ids:
        return {}
    try:
        conn = db.get_conn()
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = conn.execute(
            f"SELECT id, source_id, text FROM chunks WHERE id IN ({placeholders})",
            tuple(int(c) for c in chunk_ids),
        ).fetchall()
        return {int(r["id"]): {"text": r["text"], "source_id": int(r["source_id"])} for r in rows}
    except Exception as exc:
        log.warning("chunk fetch failed: %s", exc)
        return {}


def _rrf_fuse(rankings: list[list[int]], k: int) -> dict[int, float]:
    """Reciprocal Rank Fusion over multiple ranked id lists. id -> fused score."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _hybrid_search_sync(query: str, run_id: int, top_k: int, qvec: list[float]) -> list[dict]:
    try:
        settings = get_settings()
        rrf_k = int(settings.rrf_k)
    except Exception:
        rrf_k = 60

    rankings: list[list[int]] = []

    # (a) vector
    vec_ok = False
    try:
        vec_ok = db.vec_available()
    except Exception:
        vec_ok = False
    if vec_ok and qvec:
        vec_ranking = _vector_search_sync(qvec, run_id, k=max(top_k * 5, top_k))
        if vec_ranking:
            rankings.append(vec_ranking)

    # (b) lexical
    match = _sanitize_fts(query)
    lex_ranking = _lexical_search_sync(match, run_id, limit=max(top_k * 5, top_k))
    if lex_ranking:
        rankings.append(lex_ranking)

    if not rankings:
        return []

    fused = _rrf_fuse(rankings, rrf_k)
    if not fused:
        return []

    top_ids = sorted(fused, key=lambda c: fused[c], reverse=True)[:top_k]
    chunk_map = _fetch_chunk_rows(top_ids)

    out: list[dict] = []
    for cid in top_ids:
        row = chunk_map.get(cid)
        if not row:
            continue
        out.append({
            "chunk_id": cid,
            "source_id": row["source_id"],
            "text": row["text"],
            "score": float(fused[cid]),
        })
    return out


async def hybrid_search(query: str, run_id: int, top_k: int = 12) -> list[dict]:
    """RRF-fuse vector + lexical retrieval. Returns [{chunk_id, source_id, text, score}]."""
    try:
        qvec: list[float] = []
        try:
            if db.vec_available():
                qvec = await embedder.aembed_query(query)
        except Exception as exc:
            log.warning("query embedding failed; lexical-only: %s", exc)
            qvec = []
        return await asyncio.to_thread(_hybrid_search_sync, query, run_id, top_k, qvec)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("hybrid_search failed: %s", exc)
        return []
