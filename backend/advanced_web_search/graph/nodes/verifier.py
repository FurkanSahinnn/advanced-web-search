"""
Verifier node — adversarial citation check.

Re-checks each citation's source: DOI-backed canonical ids are treated as
alive; otherwise the URL is liveness-checked. Verdicts are persisted and
streamed. A claim whose citations are ALL dead is marked unsupported. If any
such fatal claim exists and we are under the iteration cap, the node signals a
loop back to the synthesizer.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...config import get_settings
from ...db import repositories
from ...utils.http import check_url_alive
from ..events import emit

_MAX_CITATIONS = 30


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
    checked = 0
    source_cache: dict[Any, dict] = {}

    for cl in claims:
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

            if citation_id is not None:
                verdicts[citation_id] = alive
                try:
                    await asyncio.to_thread(
                        repositories.update_citation_verdict, citation_id,
                        verified=alive, dead_link=not alive,
                    )
                except Exception:
                    pass

            emit("citation_verified", run_id, node="verifier",
                 source_id=source_id, verified=alive, dead_link=not alive, stance=stance)
        if checked >= _MAX_CITATIONS:
            break

    # A claim is fatal if it HAS citations and ALL of them are dead.
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

    return {
        "verifier_iteration": iteration + 1,
        "verifier_fatal": verifier_fatal,
        "verifier_notes": notes,
        **({"errors": errors} if errors else {}),
    }
