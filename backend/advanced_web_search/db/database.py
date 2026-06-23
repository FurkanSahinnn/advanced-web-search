"""
SQLite connection management + schema/virtual-table initialization.

One process-wide connection (WAL mode, check_same_thread=False) guards
writes with a lock; reads run concurrently. The same .db file also holds
the sqlite-vec vector table and FTS5 indexes. LangGraph checkpoints use a
separate aiosqlite connection to the same file (see graph/builder.py).

Repositories should use `tx()` for writes and `get_conn()` for reads, and
should call DB work from async code via `asyncio.to_thread(...)`.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import get_settings

_SCHEMA = Path(__file__).with_name("schema.sql")

_conn: "_SerializedConnection | None" = None
# Re-entrant so a write transaction (which holds the lock for its whole body)
# can still issue individual ``execute`` calls through the same serializing
# proxy without deadlocking.
_write_lock = threading.RLock()
_init_lock = threading.Lock()
_vec_available = False


class _BufferedCursor:
    """A cursor whose SELECT rows are fully materialized under the conn lock.

    A raw ``sqlite3`` connection is NOT safe for concurrent use across threads:
    the graph fans retrieval out with ``asyncio.to_thread`` and many branches
    drive the single shared connection at once, which interleaves cursor state
    and corrupts results ("no more rows available" / "another row available").

    To make the shared connection safe, ``_SerializedConnection`` runs every
    statement under ``_write_lock`` and returns this object, which has already
    fetched all rows (for SELECTs) so ``fetchone``/``fetchall`` need no further
    locked access to the live cursor. ``lastrowid``/``rowcount`` are captured
    for write statements.
    """

    __slots__ = ("_rows", "_idx", "lastrowid", "rowcount", "description")

    def __init__(self, rows, lastrowid, rowcount, description):
        self._rows = rows
        self._idx = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.description = description

    def fetchone(self):
        if self._idx >= len(self._rows):
            return None
        r = self._rows[self._idx]
        self._idx += 1
        return r

    def fetchall(self):
        out = self._rows[self._idx:]
        self._idx = len(self._rows)
        return out

    def fetchmany(self, size=1):
        out = self._rows[self._idx:self._idx + size]
        self._idx += len(out)
        return out

    def __iter__(self):
        while self._idx < len(self._rows):
            yield self.fetchone()


class _SerializedConnection:
    """Thread-safe proxy over the shared sqlite3 connection.

    Every ``execute``/``executemany`` acquires ``_write_lock`` for the full
    statement + row fetch, so concurrent ``asyncio.to_thread`` callers can never
    interleave on the underlying connection. Transaction control (``commit``,
    ``rollback``, ``execute('BEGIN IMMEDIATE')``) and the read helpers all go
    through here. The lock is re-entrant, so ``tx()`` may hold it across a whole
    transaction while individual statements re-acquire it.
    """

    def __init__(self, raw: sqlite3.Connection):
        self._raw = raw

    def _run(self, method: str, sql, params=None):
        with _write_lock:
            cur = getattr(self._raw, method)(sql, params) if params is not None \
                else getattr(self._raw, method)(sql)
            rows = cur.fetchall() if cur.description is not None else []
            return _BufferedCursor(rows, cur.lastrowid, cur.rowcount, cur.description)

    def execute(self, sql, params=None):
        return self._run("execute", sql, params)

    def executemany(self, sql, seq_of_params):
        with _write_lock:
            cur = self._raw.executemany(sql, seq_of_params)
            rows = cur.fetchall() if cur.description is not None else []
            return _BufferedCursor(rows, cur.lastrowid, cur.rowcount, cur.description)

    def executescript(self, script):
        with _write_lock:
            return self._raw.executescript(script)

    def commit(self):
        with _write_lock:
            return self._raw.commit()

    def rollback(self):
        with _write_lock:
            return self._raw.rollback()

    def close(self):
        with _write_lock:
            return self._raw.close()

    @property
    def row_factory(self):
        return self._raw.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._raw.row_factory = value

    def __getattr__(self, name):
        # Fall back to the raw connection for anything not overridden.
        return getattr(self._raw, name)

# A write transaction on the relational connection can briefly collide with the
# LangGraph checkpointer's aiosqlite connection (both write the same WAL file):
# SQLite returns SQLITE_BUSY ("database is locked") immediately on a writer vs
# writer conflict, BEFORE the busy_timeout handler can help. Retry a bounded
# number of times with a short backoff so a transient lock never aborts a node.
_BUSY_RETRIES = 8
_BUSY_BACKOFF = 0.05  # seconds, grows linearly per attempt


def _column_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _apply_migrations(conn) -> None:
    """Idempotently add columns introduced after the initial schema.

    Runs on the RAW sqlite3 connection inside ``init_db`` so already-existing
    databases (where ``CREATE TABLE IF NOT EXISTS`` is a no-op) gain the new
    columns. The ``CREATE INDEX`` lives here (not in schema.sql) so it only runs
    AFTER the ``language`` column exists on a migrated DB.
    """
    pcols = _column_names(conn, "projects")
    if "report_languages" not in pcols:
        conn.execute("ALTER TABLE projects ADD COLUMN report_languages TEXT")
    rcols = _column_names(conn, "reports")
    if "language" not in rcols:
        conn.execute("ALTER TABLE reports ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
    if "ord" not in rcols:
        conn.execute("ALTER TABLE reports ADD COLUMN ord INTEGER NOT NULL DEFAULT 0")
    # `ref_ids`: JSON array of source ids in [n] citation order (index+1 == n),
    # i.e. the numbered source list the synthesizer handed the LLM. Lets the UI
    # resolve an inline [n] marker to the exact source instead of guessing by
    # position, and lets exports number the bibliography to match the body.
    # (Column is named `ref_ids`, not `references`, because REFERENCES is a SQL
    # keyword.)
    if "ref_ids" not in rcols:
        conn.execute("ALTER TABLE reports ADD COLUMN ref_ids TEXT")
    # `disagreements`: a short summary of where the sources CONFLICT, contradict
    # each other, or are uncertain — the counterpart to consensus_summary. Lets
    # the report surface points of disagreement explicitly instead of burying
    # them inside the consensus prose.
    if "disagreements" not in rcols:
        conn.execute("ALTER TABLE reports ADD COLUMN disagreements TEXT")
    # `grounding`: post-verification JSON breakdown of per-verdict claim counts
    # (supported/partial/unsupported/unverifiable) + the grounded share. Written
    # by the verifier, which also rewrites `certainty` to that share so the
    # confidence meter reflects whether sources actually entail the claims (not
    # just their retrieval scores). Older rows stay NULL and fall back gracefully.
    if "grounding" not in rcols:
        conn.execute("ALTER TABLE reports ADD COLUMN grounding TEXT")
    # `quality`: post-verification reference-free quality scorecard JSON
    # (groundedness, citation precision/coverage, answer relevance, source
    # diversity, reranker_degraded, overall). A glanceable self-assessment;
    # written by the verifier. Older rows stay NULL and the UI just omits it.
    if "quality" not in rcols:
        conn.execute("ALTER TABLE reports ADD COLUMN quality TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_reports_run_lang ON reports(run_id, language)")

    # Citation entailment verdict (claim actually supported by the cited source),
    # kept SEPARATE from `verified` which means link-liveness only. `support` is
    # the verdict label; `support_score` the embedding-prefilter similarity.
    ccols = _column_names(conn, "citations")
    if "support" not in ccols:
        conn.execute("ALTER TABLE citations ADD COLUMN support TEXT")
    if "support_score" not in ccols:
        conn.execute("ALTER TABLE citations ADD COLUMN support_score REAL")


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        # Vector search degrades to FTS-only; never fatal.
        import logging

        logging.getLogger("advanced_web_search.db").warning("sqlite-vec unavailable: %s", exc)
        return False


def get_conn() -> sqlite3.Connection:
    """Return the shared, initialized connection."""
    global _conn
    if _conn is None:
        init_db()
    assert _conn is not None
    return _conn


def vec_available() -> bool:
    return _vec_available


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Serialized write transaction.

    Opens an explicit ``BEGIN IMMEDIATE`` so the writer lock is acquired up
    front (under our process-wide write lock), then commits. ``BEGIN IMMEDIATE``
    makes SQLite's busy-timeout handler actually apply to the lock acquisition,
    so a transient collision with the checkpointer's connection on the shared
    WAL file waits (up to ``busy_timeout``) instead of failing immediately with
    ``SQLITE_BUSY``. A short application-level retry covers the residual race.
    """
    conn = get_conn()
    with _write_lock:
        last_exc: BaseException | None = None
        for attempt in range(_BUSY_RETRIES):
            try:
                conn.execute("BEGIN IMMEDIATE")
            except Exception as exc:
                if _is_locked_error(exc) and attempt < _BUSY_RETRIES - 1:
                    last_exc = exc
                    time.sleep(_BUSY_BACKOFF * (attempt + 1))
                    continue
                raise
            try:
                yield conn
                conn.commit()
                return
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
        if last_exc is not None:
            raise last_exc


def run_in_tx(fn):
    """Run ``fn(conn)`` inside a write transaction, retrying the WHOLE body on a
    transient lock.

    ``tx()`` only retries acquiring ``BEGIN IMMEDIATE``; a collision with the
    checkpointer's connection on the shared WAL file can also surface part-way
    through the statements or at ``commit()``. A ``@contextmanager`` cannot
    replay its caller's ``with`` body, so callers whose transaction must be
    all-or-nothing (e.g. the subtopic rebuild that DELETEs then re-INSERTs) run
    their body through this helper instead, which re-executes the entire
    transaction on a transient ``database is locked`` error. ``fn`` must be
    idempotent across retries (it is: each attempt runs in a fresh, rolled-back
    transaction).
    """
    last_exc: BaseException | None = None
    for attempt in range(_BUSY_RETRIES):
        try:
            with tx() as conn:
                return fn(conn)
        except Exception as exc:
            if _is_locked_error(exc) and attempt < _BUSY_RETRIES - 1:
                last_exc = exc
                time.sleep(_BUSY_BACKOFF * (attempt + 1))
                continue
            raise
    if last_exc is not None:
        raise last_exc


def _is_locked_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def init_db() -> "_SerializedConnection":
    """Create the connection, apply schema, build FTS5 + vec0 virtual tables.

    The returned connection is a ``_SerializedConnection`` proxy so the single
    shared sqlite3 handle is safe to drive from the many ``asyncio.to_thread``
    workers the graph spawns (a raw connection used concurrently corrupts cursor
    state). Setup runs on the raw handle, then it is wrapped.
    """
    global _conn, _vec_available
    with _init_lock:
        if _conn is not None:
            return _conn

        settings = get_settings()
        db_path = settings.db_path
        # isolation_level=None -> autocommit mode: we manage transactions
        # explicitly via BEGIN IMMEDIATE / COMMIT in tx(), which lets the
        # busy-timeout handler apply to writer-lock acquisition (avoids the
        # immediate SQLITE_BUSY that a deferred transaction's mid-statement
        # lock upgrade can hit when the checkpointer holds the WAL writer).
        conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=8000;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        _vec_available = _load_sqlite_vec(conn)

        # 1) relational schema
        conn.executescript(_SCHEMA.read_text(encoding="utf-8"))

        # 1b) idempotent column migrations for already-existing DBs
        _apply_migrations(conn)

        # 2) full-text indexes (external-content FTS5 + sync triggers)
        conn.executescript(_FTS_DDL)

        # 3) vector table (only if the extension loaded)
        if _vec_available:
            conn.executescript(_VEC_DDL.format(dim=settings.embed_dim))

        conn.commit()
        _conn = _SerializedConnection(conn)
        return _conn


_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
    title, abstract, content='sources', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS sources_ai AFTER INSERT ON sources BEGIN
    INSERT INTO sources_fts(rowid, title, abstract) VALUES (new.id, new.title, new.abstract);
END;
CREATE TRIGGER IF NOT EXISTS sources_ad AFTER DELETE ON sources BEGIN
    INSERT INTO sources_fts(sources_fts, rowid, title, abstract) VALUES ('delete', old.id, old.title, old.abstract);
END;
CREATE TRIGGER IF NOT EXISTS sources_au AFTER UPDATE ON sources BEGIN
    INSERT INTO sources_fts(sources_fts, rowid, title, abstract) VALUES ('delete', old.id, old.title, old.abstract);
    INSERT INTO sources_fts(rowid, title, abstract) VALUES (new.id, new.title, new.abstract);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

# vec0 virtual table keyed by chunks.id (rowid). `dim` filled from settings.
_VEC_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    source_id INTEGER,
    embedding FLOAT[{dim}]
);
"""
