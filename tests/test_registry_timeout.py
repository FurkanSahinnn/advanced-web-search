"""A hung source provider must never stall the search fan-out.

Locks the per-provider ``asyncio.wait_for`` backstop in ``registry.search_all``:
one provider whose ``search()`` never returns (the real-world case is
DuckDuckGo's ddgs running in a non-cancellable thread) is capped and degraded to
``[]`` while the other providers' results still come back. Without the timeout
the gather — and the whole researcher node / run — would hang forever.
"""

from __future__ import annotations

import asyncio

from advanced_web_search.sources import registry
from advanced_web_search.sources.base import SourceCandidate, SourceProvider

# The autouse ``patch_seams`` fixture (conftest.py) replaces registry.search_all
# with an offline fake. Capture the REAL implementation at import time (before
# any fixture runs) so this test exercises the actual per-provider timeout.
_REAL_SEARCH_ALL = registry.search_all


class _HangProvider(SourceProvider):
    name = "hang"
    kind = "web"

    async def search(self, query, *, limit=8, since=None, language=None):
        await asyncio.Event().wait()  # never resolves
        return []  # pragma: no cover


class _FastProvider(SourceProvider):
    name = "fast"
    kind = "web"

    async def search(self, query, *, limit=8, since=None, language=None):
        return [
            SourceCandidate(
                title="ok", url="https://example.org/x", provider=self.name, kind="web"
            ).normalize()
        ]


async def test_one_hung_provider_does_not_stall_search_all(monkeypatch):
    fakes = [_HangProvider(), _FastProvider()]
    monkeypatch.setattr(registry, "enabled_providers", lambda kind=None: fakes)

    # Outer guard: if the per-provider timeout regressed, search_all would hang
    # and this wait_for would fail the test fast instead of blocking the suite.
    out = await asyncio.wait_for(
        _REAL_SEARCH_ALL("q", kinds=("web",), timeout=0.2),
        timeout=5,
    )

    providers = {c.provider for c in out}
    assert "fast" in providers  # the bounded provider's results survive
    assert "hang" not in providers  # the wedged provider degraded to []
