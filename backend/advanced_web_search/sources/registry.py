"""Source provider registry + fan-out search.

Instantiates every connector, exposes filtering by kind, and runs an enabled
subset concurrently. Deduplication is intentionally NOT done here — see
retrieval/dedup.py (canonicalize + merge happens downstream).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from .academic_arxiv import ArxivProvider
from .academic_core import CoreProvider
from .academic_crossref import CrossrefProvider
from .academic_doaj import DoajProvider
from .academic_europepmc import EuropePmcProvider
from .academic_openalex import OpenAlexProvider
from .academic_pubmed import PubMedProvider
from .academic_semanticscholar import SemanticScholarProvider
from .academic_unpaywall import UnpaywallProvider
from .base import SourceCandidate, SourceProvider
from .web_brave import BraveProvider
from .web_duckduckgo import DuckDuckGoProvider
from .web_searxng import SearxngProvider
from .web_tavily import TavilyProvider

# Providers whose search() is a known no-op (enrichers); excluded from discovery.
_NO_DISCOVERY = {"unpaywall"}

log = logging.getLogger("advanced_web_search.sources.registry")

# Hard per-provider deadline for the search fan-out. A provider that never
# returns (e.g. DuckDuckGo's ddgs running in a NON-cancellable asyncio.to_thread
# that blocks on a wedged engine / shutdown(wait=True)) must not stall the whole
# gather — and thus the researcher node and the entire run. 30s is generous for
# the bounded utils/http.py providers (which finish in seconds; only a
# pathological retry-storm approaches it) while still capping a true hang.
# wait_for frees the awaiting coroutine on timeout; a to_thread worker it spawned
# keeps running in the background until it unwinds (threads aren't cancellable) —
# acceptable: the run proceeds with the other providers' results.
_PROVIDER_TIMEOUT = 30.0


def all_providers() -> list[SourceProvider]:
    """Instantiate every provider (no network, no key checks)."""
    return [
        # web
        DuckDuckGoProvider(),
        SearxngProvider(),
        TavilyProvider(),
        BraveProvider(),
        # academic / preprint
        ArxivProvider(),
        CrossrefProvider(),
        EuropePmcProvider(),
        OpenAlexProvider(),
        SemanticScholarProvider(),
        DoajProvider(),
        PubMedProvider(),
        CoreProvider(),
        UnpaywallProvider(),
    ]


def _kind_matches(provider_kind: str, requested: Optional[str]) -> bool:
    if requested is None:
        return True
    if requested == "academic":
        return provider_kind in ("academic", "preprint")
    if requested == "web":
        return provider_kind == "web"
    return provider_kind == requested


def enabled_providers(kind: Optional[str] = None) -> list[SourceProvider]:
    """Enabled providers, optionally filtered by kind.

    `kind="academic"` also includes preprint providers; `kind="web"` matches
    web providers only.
    """
    out: list[SourceProvider] = []
    for p in all_providers():
        try:
            if not p.enabled():
                continue
        except Exception:
            continue
        if _kind_matches(p.kind, kind):
            out.append(p)
    return out


async def search_all(
    query: str,
    *,
    kinds: tuple[str, ...] = ("web", "academic"),
    per_provider_limit: int = 8,
    since: Optional[date] = None,
    language: Optional[str] = None,
    timeout: Optional[float] = None,
) -> list[SourceCandidate]:
    """Fan out search() across enabled providers matching `kinds`, concurrently.

    Returns the flat, combined list of candidates (NOT deduped). Exceptions and
    None results are dropped. Known no-op enrichers (unpaywall) are excluded.
    """
    seen: dict[int, SourceProvider] = {}
    providers: list[SourceProvider] = []
    for k in kinds:
        for p in enabled_providers(k):
            if p.name in _NO_DISCOVERY:
                continue
            if id(p) in seen:
                continue
            seen[id(p)] = p
            providers.append(p)

    if not providers:
        return []

    deadline = _PROVIDER_TIMEOUT if timeout is None else timeout

    async def _run(p: SourceProvider) -> list[SourceCandidate]:
        try:
            return await asyncio.wait_for(
                p.search(
                    query,
                    limit=per_provider_limit,
                    since=since,
                    language=language,
                ),
                timeout=deadline,
            )
        except asyncio.TimeoutError:
            # One hung provider must not park the whole gather (see _PROVIDER_TIMEOUT).
            log.warning("provider %s timed out after %ss; skipped",
                        getattr(p, "name", "?"), deadline)
            return []
        except Exception:
            return []

    results = await asyncio.gather(
        *(_run(p) for p in providers), return_exceptions=True
    )

    combined: list[SourceCandidate] = []
    for res in results:
        if isinstance(res, BaseException) or res is None:
            continue
        for cand in res:
            if cand is not None:
                combined.append(cand)
    return combined
