"""Source provider registry + fan-out search.

Instantiates every connector, exposes filtering by kind, and runs an enabled
subset concurrently. Deduplication is intentionally NOT done here — see
retrieval/dedup.py (canonicalize + merge happens downstream).
"""

from __future__ import annotations

import asyncio
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

    async def _run(p: SourceProvider) -> list[SourceCandidate]:
        try:
            return await p.search(
                query,
                limit=per_provider_limit,
                since=since,
                language=language,
            )
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
