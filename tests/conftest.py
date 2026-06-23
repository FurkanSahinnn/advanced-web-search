"""
Offline, model-free end-to-end test harness for the Advanced Web Search research graph.

We mock ONLY the external boundaries (LLM calls, source search, snowball,
embeddings, reranker, HTTP) and run the REAL graph / DB / scoring / retrieval /
SSE / export end to end.

Critical ordering: AWSEARCH_DATA_DIR must be set in the environment BEFORE any
advanced_web_search module reads settings, so we set it at import time (module top-level)
pointing at a temp dir. Each test then gets its OWN fresh data dir + DB +
freshly-built graph bound to that test's event loop.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

# --- set the data dir BEFORE importing any advanced_web_search module ---------------------
_SESSION_ROOT = Path(tempfile.mkdtemp(prefix="aws-tests-"))
os.environ["AWSEARCH_DATA_DIR"] = str(_SESSION_ROOT / "boot")
# Make sure no real cloud provider key leaks into the run (forces local model
# path, which we fully mock anyway via provider.chat_* patches).
for _k in (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "GROQ_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
    "TAVILY_API_KEY", "BRAVE_API_KEY", "CORE_API_KEY",
):
    os.environ.pop(_k, None)


# --------------------------------------------------------------------------- #
# Deterministic fakes for the external seams
# --------------------------------------------------------------------------- #

def _fake_candidates():
    """~9 deterministic SourceCandidate objects (web + academic mix)."""
    from advanced_web_search.sources.base import SourceCandidate

    cands: list[SourceCandidate] = []

    # 5 web hits
    for i in range(1, 6):
        cands.append(
            SourceCandidate(
                title=f"Web source {i} on the topic",
                url=f"https://example.com/web-{i}",
                provider="duckduckgo",
                kind="web",
                abstract=f"A web overview number {i} discussing the research question in depth.",
                published_date=f"202{i % 4}-03-1{i % 9}",
            ).normalize()
        )

    # 4 academic hits (with DOI / citations)
    for i in range(1, 5):
        cands.append(
            SourceCandidate(
                title=f"Academic paper {i}: a study",
                url=f"https://doi.org/10.1234/abc{i}",
                provider="openalex",
                kind="academic",
                abstract=(
                    f"Peer-reviewed study {i}. We present a meta-analysis with strong evidence "
                    "addressing the sub-question comprehensively."
                ),
                published_date=f"2022-0{i}-15",
                doi=f"10.1234/abc{i}",
                venue="Journal of Testing",
                cited_by_count=10 * i,
                is_oa=True,
            ).normalize()
        )
    return cands


async def _fake_search_all(query, *, kinds=("web", "academic"),
                           per_provider_limit=8, since=None, language=None):
    return _fake_candidates()


async def _fake_expand_citations(seeds, *, per_seed=8, total_limit=60):
    from advanced_web_search.sources.base import SourceCandidate

    return [
        SourceCandidate(
            title="Snowballed citing work",
            url="https://doi.org/10.5678/snow1",
            provider="openalex-snowball",
            kind="academic",
            abstract="A work discovered via citation snowballing.",
            published_date="2023-01-01",
            doi="10.5678/snow1",
            cited_by_count=5,
            is_oa=True,
        ).normalize()
    ]


# --- LLM seam: content-aware fakes ------------------------------------------ #

def _messages_text(messages) -> str:
    parts = []
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if c:
            parts.append(str(c))
    return "\n".join(parts)


async def _fake_chat_json(role, messages, *, temperature=0.2, max_tokens=None, retries=2):
    text = _messages_text(messages)

    # Verifier entailment judge: {"verdict": ..., "quote": ...}
    if "SOURCE PASSAGE" in text or "supports a CLAIM" in text:
        return {"verdict": "supported", "quote": "a short backing quote"}

    # Synthesizer Self-Refine critique: {"issues": [...]} — return none so the
    # deterministic test report is never rewritten by the revise pass.
    if "Critique the DRAFT" in text:
        return {"issues": []}

    # Researcher query-expansion: {"queries":[...]}
    if "ALTERNATIVE search queries" in text or '"queries"' in text and "translation" in text:
        return {"queries": ["alt query one", "alt query two"]}

    # Gap follow-up proposal: {"queries":[{question,parent_id,perspective}]}
    if "UNDER-COVERED SUB-QUESTIONS" in text or "follow-up sub-questions" in text:
        return {"queries": [
            {"question": "Follow-up gap sub-question A?", "parent_id": None,
             "perspective": "gap follow-up"},
            {"question": "Follow-up gap sub-question B?", "parent_id": None,
             "perspective": "gap follow-up"},
        ]}

    # Gap dynamic outline revision: {"add":[{question,perspective}]} — return no
    # new angles so the deterministic subtopic tree stays stable (the real
    # parse/dedup path is still exercised).
    if "OVERLOOKED" in text or "RESEARCH GOAL" in text:
        return {"add": []}

    # Synthesizer claim extraction: array of {text, subtopic_id, citations:[{n,stance}]}
    if "extract the key factual claims" in text or "atomic factual claims" in text:
        return [
            {"text": "The first key finding is well supported.",
             "subtopic_id": None,
             "citations": [{"n": 1, "stance": "supporting"},
                           {"n": 2, "stance": "supporting"}]},
            {"text": "A second finding holds across sources.",
             "subtopic_id": None,
             "citations": [{"n": 2, "stance": "neutral"}]},
        ]

    # Moderator gap pass: 1-2 additional angles
    if "under-covered angles" in text or "ADDITIONAL under-covered" in text:
        return [
            {"question": "What is an under-covered angle?",
             "perspective": "moderator angle",
             "rationale": "fills a coverage gap"},
        ]

    # Planner: a JSON list of ~5 sub-questions
    if "Decompose this" in text or "ROOT QUESTION" in text:
        return [
            {"question": f"Sub-question {i}?", "perspective": f"angle {i}",
             "rationale": f"because {i}", "parent": None, "depth": 0}
            for i in range(1, 6)
        ]

    # Default: empty list (safe)
    return []


async def _fake_chat(role, messages, *, temperature=0.3, max_tokens=None, json_mode=False):
    return "Fake completion with citation [1] and [2]."


async def _fake_chat_stream(role, messages, *, temperature=0.3, max_tokens=None):
    tokens = [
        "## Findings\n\n",
        "The evidence shows a clear pattern [1]. ",
        "Multiple sources converge on this conclusion [2]. ",
        "There is some disagreement on the details [1][2].\n\n",
        "## Consensus\n\n",
        "Overall the sources broadly agree, with minor caveats [1].",
    ]
    for t in tokens:
        yield t


# --- embeddings / reranker seam --------------------------------------------- #

def _fake_embed_texts(texts):
    from advanced_web_search.config import get_settings

    dim = get_settings().embed_dim
    out = []
    for i, t in enumerate(texts or []):
        # deterministic, non-zero vector of the correct dim
        base = (abs(hash(t)) % 97 + 1) / 100.0
        out.append([base + (j % 5) * 0.001 for j in range(dim)])
    return out


def _fake_embed_query(text):
    out = _fake_embed_texts([text])
    return out[0] if out else []


async def _fake_aembed_texts(texts):
    return _fake_embed_texts(texts)


async def _fake_aembed_query(text):
    return _fake_embed_query(text)


def _fake_rerank(query, docs):
    n = len(docs or [])
    return [max(0.0, 1.0 - 0.01 * i) for i in range(n)]


async def _fake_arerank(query, docs):
    return _fake_rerank(query, docs)


# --- HTTP seam -------------------------------------------------------------- #

async def _fake_fetch_text(url, *, headers=None, retries=2, timeout=25.0):
    return (
        "<html><body><article>"
        + ("This is fake fetched article text with enough length to pass the "
           "minimum-length gate used by the researcher full-text path. " * 6)
        + "</article></body></html>"
    )


async def _fake_fetch_bytes(url, *, headers=None, retries=2, max_bytes=8_000_000):
    return b"%PDF-1.4 fake pdf bytes"


async def _fake_check_url_alive(url):
    return (True, 200)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def fresh_env(monkeypatch):
    """Give each test a fresh temp data dir + DB + freshly-built graph.

    Resets:
      * advanced_web_search.config.get_settings cache (so AWSEARCH_DATA_DIR is re-read),
      * advanced_web_search.db.database module globals (so init_db builds a fresh temp DB),
      * the builder's cached compiled graph + checkpointer singleton (so the
        graph is built in THIS test's event loop).
    """
    data_dir = _SESSION_ROOT / f"case-{uuid.uuid4().hex}"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AWSEARCH_DATA_DIR", str(data_dir))

    from advanced_web_search.config import get_settings
    get_settings.cache_clear()

    # Reset the relational DB singleton so init_db() builds a fresh temp DB.
    from advanced_web_search.db import database
    if database._conn is not None:
        try:
            database._conn.close()
        except Exception:
            pass
    database._conn = None
    database._vec_available = False

    # Initialize a brand-new DB at the fresh path.
    database.init_db()

    yield data_dir

    # Teardown: close the relational connection so the next test rebuilds it.
    if database._conn is not None:
        try:
            database._conn.close()
        except Exception:
            pass
    database._conn = None


@pytest.fixture(autouse=True)
def patch_seams(monkeypatch):
    """Patch every external boundary with a deterministic fake.

    Patched where USED (verified against the source imports):
      * provider.chat_json / chat / chat_stream  (module-level functions)
      * researcher.registry.search_all           (researcher does `registry.search_all`)
      * snowball.expand_citations                (researcher imports it locally)
      * embedder.* and reranker.*                (used by vector_store + scoring)
      * researcher.fetch_text                    (`from ...utils.http import fetch_text`)
      * verifier.check_url_alive                 (`from ...utils.http import check_url_alive`)
    """
    import importlib

    from advanced_web_search.llm import provider
    # NOTE: `advanced_web_search.graph.nodes.__init__` re-exports each node FUNCTION under the
    # submodule's name (e.g. attribute `researcher` is the function), which
    # shadows the submodule when accessed as an attribute. Use importlib to fetch
    # the actual MODULE objects so we patch the names where each node looked them
    # up.
    researcher_node = importlib.import_module("advanced_web_search.graph.nodes.researcher")
    verifier_node = importlib.import_module("advanced_web_search.graph.nodes.verifier")
    planner_node = importlib.import_module("advanced_web_search.graph.nodes.planner")
    moderator_node = importlib.import_module("advanced_web_search.graph.nodes.moderator")
    gap_node = importlib.import_module("advanced_web_search.graph.nodes.gap")
    synth_node = importlib.import_module("advanced_web_search.graph.nodes.synthesizer")
    from advanced_web_search.sources import snowball
    from advanced_web_search.embeddings import embedder
    from advanced_web_search.embeddings import reranker
    from advanced_web_search.utils import http

    # LLM
    monkeypatch.setattr(provider, "chat_json", _fake_chat_json)
    monkeypatch.setattr(provider, "chat", _fake_chat)
    monkeypatch.setattr(provider, "chat_stream", _fake_chat_stream)
    # Nodes that imported the names directly:
    monkeypatch.setattr(researcher_node, "chat_json", _fake_chat_json)
    monkeypatch.setattr(planner_node, "chat_json", _fake_chat_json)
    monkeypatch.setattr(moderator_node, "chat_json", _fake_chat_json)
    monkeypatch.setattr(gap_node, "chat_json", _fake_chat_json)
    monkeypatch.setattr(synth_node, "chat_json", _fake_chat_json)
    monkeypatch.setattr(synth_node, "chat_stream", _fake_chat_stream)
    monkeypatch.setattr(synth_node, "chat", _fake_chat)
    # Verifier imported chat_json directly; fake it so entailment stays offline
    # and deterministic (incl. the multi-sample self-consistency path).
    monkeypatch.setattr(verifier_node, "chat_json", _fake_chat_json)

    # Sources: researcher uses `registry.search_all`
    monkeypatch.setattr(researcher_node.registry, "search_all", _fake_search_all)
    # Snowball expand_citations (imported locally inside _snowball)
    monkeypatch.setattr(snowball, "expand_citations", _fake_expand_citations)

    # Embeddings + reranker (deterministic, no model download)
    monkeypatch.setattr(embedder, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(embedder, "embed_query", _fake_embed_query)
    monkeypatch.setattr(embedder, "aembed_texts", _fake_aembed_texts)
    monkeypatch.setattr(embedder, "aembed_query", _fake_aembed_query)
    monkeypatch.setattr(reranker, "rerank", _fake_rerank)
    monkeypatch.setattr(reranker, "arerank", _fake_arerank)

    # HTTP
    monkeypatch.setattr(researcher_node, "fetch_text", _fake_fetch_text)
    monkeypatch.setattr(verifier_node, "fetch_text", _fake_fetch_text)
    monkeypatch.setattr(verifier_node, "check_url_alive", _fake_check_url_alive)
    monkeypatch.setattr(http, "fetch_text", _fake_fetch_text)
    monkeypatch.setattr(http, "fetch_bytes", _fake_fetch_bytes)
    monkeypatch.setattr(http, "check_url_alive", _fake_check_url_alive)


@pytest.fixture
async def reset_graph():
    """Drop the cached compiled graph before AND after a test so it binds to the
    test's own event loop."""
    from advanced_web_search.graph import builder

    await builder.reset()
    yield
    await builder.reset()


def set_db_setting(key: str, value: Any) -> None:
    from advanced_web_search.db import repositories
    repositories.set_setting(key, value)
