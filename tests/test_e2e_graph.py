"""
End-to-end tests that RUN the full Advanced Web Search research graph offline (model-free).

Only external boundaries are faked (see conftest.py); the real graph, DB,
scoring, retrieval, SSE event stream and export are exercised.
"""

from __future__ import annotations

import asyncio

import pytest

from advanced_web_search.db import repositories


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_project_and_run(root_query: str, language: str = "en"):
    project_id = repositories.create_project("Test project", root_query, language)
    run = repositories.create_run(project_id)
    return project_id, run["id"]


def _types(events):
    return [e.get("type") for e in events]


def _flatten_tree(tree):
    out = []
    for node in tree or []:
        out.append(node)
        out.extend(_flatten_tree(node.get("children")))
    return out


# --------------------------------------------------------------------------- #
# 1) Full run, no approval
# --------------------------------------------------------------------------- #

async def test_full_run_no_approval(fresh_env, reset_graph):
    from advanced_web_search.graph import runner

    # Standard depth, approval off — set via persisted settings (DB).
    repositories.set_setting("require_approval", False)
    repositories.set_setting("depth", "standard")

    project_id, run_id = _make_project_and_run("What are the effects of X on Y?")

    events = [e async for e in runner.run_stream(run_id)]
    types = set(_types(events))

    # Event stream assertions
    assert "run_started" in types
    assert "plan" in types
    assert "source_found" in types
    assert "source_scored" in types
    assert "token" in types
    assert "report" in types
    assert "run_finished" in types

    # Run reached done
    run = repositories.get_run(run_id)
    assert run["status"] == "done"

    # DB durable artifacts
    subtopics = repositories.get_subtopics(project_id)
    assert len(subtopics) >= 1

    sources = repositories.get_sources(run_id)
    assert len(sources) >= 1

    # at least one source_score row (kept flag present)
    scored = [s for s in sources if s.get("final_score") is not None]
    assert len(scored) >= 1

    report = repositories.get_report(run_id)
    assert report is not None
    assert report["markdown"].strip()

    # report or a claim references a citation marker
    claims = repositories.get_claims(run_id)
    has_citation = "[1]" in report["markdown"] or "[2]" in report["markdown"]
    has_claim_citation = any(c.get("citations") for c in claims)
    assert has_citation or has_claim_citation


# --------------------------------------------------------------------------- #
# 2) HITL approval
# --------------------------------------------------------------------------- #

async def test_hitl_approval(fresh_env, reset_graph):
    from advanced_web_search.graph import runner

    repositories.set_setting("require_approval", True)
    repositories.set_setting("depth", "standard")

    project_id, run_id = _make_project_and_run("How does Z influence W?")

    # First pass: should pause at approval.
    events1 = [e async for e in runner.run_stream(run_id)]
    types1 = _types(events1)
    assert "awaiting_approval" in types1

    # Pull the emitted subtopic tree from the awaiting_approval frame.
    awaiting = next(e for e in events1 if e.get("type") == "awaiting_approval")
    tree = awaiting["data"].get("subtopics") or []
    flat = _flatten_tree(tree)
    assert flat, "approval tree should not be empty"

    approved = [
        {"id": n["id"], "parent_id": n.get("parent_id"),
         "question": n.get("question"), "keep": True}
        for n in flat if isinstance(n.get("id"), int)
    ]

    # Approve and resume.
    await runner.approve(run_id, {"approved_subtopics": approved, "extra_instructions": ""})

    events2 = [e async for e in runner.run_stream(run_id)]
    types2 = set(_types(events2))
    assert "report" in types2
    assert "run_finished" in types2

    run = repositories.get_run(run_id)
    assert run["status"] == "done"

    report = repositories.get_report(run_id)
    assert report is not None and report["markdown"].strip()


# --------------------------------------------------------------------------- #
# 3) Iterative gap loop (deep)
# --------------------------------------------------------------------------- #

async def test_iterative_loop(fresh_env, reset_graph):
    from advanced_web_search.graph import runner

    repositories.set_setting("require_approval", False)
    repositories.set_setting("depth", "deep")
    # Force the gap loop: require many kept sources per subtopic so every leaf
    # is "under-covered" and a 2nd research round is triggered.
    repositories.set_setting("gap_min_sources", 99)
    repositories.set_setting("max_research_rounds", 3)

    project_id, run_id = _make_project_and_run("Comprehensive deep question about A?")

    subtopics_before = len(repositories.get_subtopics(project_id))

    events = [e async for e in runner.run_stream(run_id)]

    # gap_analyzer must have run.
    gap_started = [
        e for e in events
        if e.get("node") == "gap_analyzer" and e.get("type") == "node_started"
    ]
    assert gap_started, "gap_analyzer node did not run"

    # A 2nd research round must have happened: researcher emits a node_started
    # whose message names round 2.
    researcher_rounds = [
        e for e in events
        if e.get("node") == "researcher" and e.get("type") == "node_started"
        and "round 2" in (e.get("message") or "")
    ]
    assert researcher_rounds, "no second research round occurred"

    # Bounded: the researcher must never exceed max_research_rounds (3).
    max_round_seen = 0
    for e in events:
        msg = e.get("message") or ""
        if e.get("node") == "researcher" and e.get("type") == "node_started":
            import re
            m = re.search(r"round (\d+)", msg)
            if m:
                max_round_seen = max(max_round_seen, int(m.group(1)))
    assert max_round_seen <= 3

    # New gap-driven subtopics were appended.
    subtopics_after = len(repositories.get_subtopics(project_id))
    assert subtopics_after > subtopics_before

    run = repositories.get_run(run_id)
    assert run["status"] == "done"


# --------------------------------------------------------------------------- #
# 4) Cancel
# --------------------------------------------------------------------------- #

async def test_cancel(fresh_env, reset_graph):
    from advanced_web_search.graph import runner

    repositories.set_setting("require_approval", False)
    repositories.set_setting("depth", "standard")

    project_id, run_id = _make_project_and_run("A question to cancel?")

    # Cancel sets status cancelled immediately.
    await runner.cancel(run_id)
    run = repositories.get_run(run_id)
    assert run["status"] == "cancelled"

    # A (re-)opened stream for a cancelled run is terminal: it reports cancelled
    # and STOPS, rather than clearing the flag and resurrecting the run from the
    # checkpoint's pending tasks (which would otherwise re-emit awaiting_approval
    # on the browser's EventSource auto-reconnect). It must not hang or raise.
    events = [e async for e in runner.run_stream(run_id)]
    assert events, "run_stream should yield at least one frame"
    finished = [e for e in events if e.get("type") == "run_finished"]
    assert finished, "expected a run_finished frame"
    assert finished[-1].get("data", {}).get("status") == "cancelled"
    assert "awaiting_approval" not in _types(events)
    assert repositories.get_run(run_id)["status"] == "cancelled"


async def test_cancel_mid_stream(fresh_env, reset_graph):
    """Cancelling WHILE a run streams ends it as cancelled (not done)."""
    from advanced_web_search.graph import runner

    repositories.set_setting("require_approval", False)
    repositories.set_setting("depth", "standard")

    project_id, run_id = _make_project_and_run("Cancel me mid-run?")

    seen = []
    async for ev in runner.run_stream(run_id):
        seen.append(ev)
        # Fire the cancel as soon as the run announces itself.
        if ev.get("type") == "run_started":
            await runner.cancel(run_id)
        if ev.get("type") == "run_finished":
            break

    finished = [e for e in seen if e.get("type") == "run_finished"]
    assert finished, "stream must terminate with a run_finished frame"
    assert finished[-1].get("data", {}).get("status") == "cancelled"
    assert repositories.get_run(run_id)["status"] == "cancelled"
    # A cancelled run must not have produced a final report.
    assert repositories.get_report(run_id) is None


# --------------------------------------------------------------------------- #
# 5) Export after a run
# --------------------------------------------------------------------------- #

async def test_export_after_run(fresh_env, reset_graph):
    from advanced_web_search.graph import runner
    from advanced_web_search import export as export_mod

    repositories.set_setting("require_approval", False)
    repositories.set_setting("depth", "standard")

    project_id, run_id = _make_project_and_run("Question for export?")

    _ = [e async for e in runner.run_stream(run_id)]

    run = repositories.get_run(run_id)
    assert run["status"] == "done"

    sources = repositories.get_sources(run_id)
    assert sources, "expected sources to export"

    bibtex = export_mod.to_bibtex(sources)
    assert bibtex.strip()
    assert "@" in bibtex


# --------------------------------------------------------------------------- #
# 6) Multi-language report (selectable report output languages)
# --------------------------------------------------------------------------- #

async def test_multi_language_report(fresh_env, reset_graph):
    """A run with report_languages=["en","tr"] produces one report per language."""
    from advanced_web_search.graph import runner

    repositories.set_setting("require_approval", False)
    repositories.set_setting("depth", "standard")

    project_id = repositories.create_project(
        "Test project", "What are the effects of X on Y?",
        "en", ["en", "tr"],
    )
    run = repositories.create_run(project_id)
    run_id = run["id"]

    events = [e async for e in runner.run_stream(run_id)]
    types = set(_types(events))
    assert "report" in types
    assert "run_finished" in types

    run = repositories.get_run(run_id)
    assert run["status"] == "done"

    reports = repositories.get_reports(run_id)
    assert len(reports) == 2
    langs = {r.get("language") for r in reports}
    assert "en" in langs
    assert "tr" in langs
