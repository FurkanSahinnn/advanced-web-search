-- =====================================================================
-- Advanced Web Search relational schema (SQLite, WAL mode).
-- Plain tables + indexes only. The vector (vec0) and full-text (fts5)
-- virtual tables are created at runtime by retrieval/vector_store.py
-- AFTER the sqlite-vec extension is loaded. LangGraph checkpoint tables
-- are created and owned by langgraph-checkpoint-sqlite.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- Top-level research project: one root question.
CREATE TABLE IF NOT EXISTS projects (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    root_query       TEXT    NOT NULL,
    language         TEXT    NOT NULL DEFAULT 'auto',   -- 'auto' | 'tr' | 'en' | ... (search hint)
    report_languages TEXT,                              -- JSON array of report output langs (nullable)
    status           TEXT    NOT NULL DEFAULT 'created', -- created|planning|awaiting_approval|running|done|error
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Nested sub-question decomposition tree (parent_id => self-reference).
CREATE TABLE IF NOT EXISTS subtopics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_id   INTEGER REFERENCES subtopics(id) ON DELETE CASCADE,
    question    TEXT    NOT NULL,
    perspective TEXT,                              -- STORM-style angle/persona
    rationale   TEXT,
    depth       INTEGER NOT NULL DEFAULT 0,
    ord         INTEGER NOT NULL DEFAULT 0,
    approved    INTEGER NOT NULL DEFAULT 0,        -- 0/1, set by HITL gate
    status      TEXT    NOT NULL DEFAULT 'pending' -- pending|researching|done
);
CREATE INDEX IF NOT EXISTS ix_subtopics_project ON subtopics(project_id);
CREATE INDEX IF NOT EXISTS ix_subtopics_parent  ON subtopics(parent_id);

-- One execution of the research graph for a project.
CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    thread_id      TEXT    NOT NULL,               -- LangGraph checkpoint thread id
    status         TEXT    NOT NULL DEFAULT 'running', -- running|awaiting_approval|done|error|cancelled
    error          TEXT,
    started_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_project ON runs(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_thread ON runs(thread_id);

-- Deduplicated retrieved sources (canonical_id = DOI / arXiv-id / normalized URL).
CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    subtopic_id    INTEGER REFERENCES subtopics(id) ON DELETE SET NULL,
    canonical_id   TEXT    NOT NULL,               -- doi:.. | arxiv:.. | url:..
    kind           TEXT    NOT NULL DEFAULT 'web', -- web|academic|preprint|dataset|code
    provider       TEXT,                           -- arxiv|crossref|openalex|duckduckgo|...
    title          TEXT,
    authors        TEXT,                            -- JSON array string
    venue          TEXT,
    published_date TEXT,
    url            TEXT,
    pdf_url        TEXT,
    abstract       TEXT,
    full_text      TEXT,
    cited_by_count INTEGER,
    is_oa          INTEGER NOT NULL DEFAULT 0,
    raw            TEXT,                            -- JSON of provider payload
    fetched_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_sources_run ON sources(run_id);
CREATE INDEX IF NOT EXISTS ix_sources_subtopic ON sources(subtopic_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sources_run_canonical ON sources(run_id, canonical_id);

-- Transparent multi-signal scoring, one row per source.
CREATE TABLE IF NOT EXISTS source_scores (
    source_id        INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    relevance        REAL NOT NULL DEFAULT 0,
    authority        REAL NOT NULL DEFAULT 0,
    recency          REAL NOT NULL DEFAULT 0,
    citation_impact  REAL NOT NULL DEFAULT 0,
    evidence         REAL NOT NULL DEFAULT 0,
    final_score      REAL NOT NULL DEFAULT 0,
    match_score      INTEGER NOT NULL DEFAULT 0,   -- 0-100 intuitive headline score
    evidence_type    TEXT,                          -- meta_analysis|rct|peer_reviewed|preprint|news|blog
    kept             INTEGER NOT NULL DEFAULT 1,
    why_kept         TEXT,                          -- one-line rationale chip
    breakdown        TEXT                           -- JSON: per-criterion detail + supporting quote
);

-- Chunked source text (for embeddings + chunk-level lexical search).
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL DEFAULT 0,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(source_id);

-- Synthesized assertions made in the report.
CREATE TABLE IF NOT EXISTS claims (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    subtopic_id  INTEGER REFERENCES subtopics(id) ON DELETE SET NULL,
    text         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'supported'  -- supported|unsupported|removed
);
CREATE INDEX IF NOT EXISTS ix_claims_run ON claims(run_id);

-- Claim -> source links, annotated by the adversarial Verifier.
CREATE TABLE IF NOT EXISTS citations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id         INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    source_id        INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    stance           TEXT NOT NULL DEFAULT 'supporting', -- supporting|contrasting|mentioning
    supporting_quote TEXT,
    verified         INTEGER NOT NULL DEFAULT 0,
    dead_link        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_citations_claim ON citations(claim_id);

-- Final cited output of a run. One row per (run, language); newest wins.
-- `ord` gives primary-first ordering (ord=0 = primary report).
CREATE TABLE IF NOT EXISTS reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    markdown          TEXT NOT NULL,
    language          TEXT NOT NULL DEFAULT 'en',      -- report output language code
    ord               INTEGER NOT NULL DEFAULT 0,      -- primary-first ordering (0 = primary)
    consensus_summary TEXT,
    comprehensiveness REAL,                          -- 0-1 coverage indicator
    certainty         REAL,                          -- 0-1 confidence indicator
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_reports_run ON reports(run_id);

-- Key-value app settings (persisted overrides: model map, weights, toggles).
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                              -- JSON
);
