"""DuckDuckGo web search provider (keyless) via the `ddgs` package."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider


class DuckDuckGoProvider(SourceProvider):
    name = "duckduckgo"
    kind = "web"
    requires_key = False

    def enabled(self) -> bool:
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        try:
            rows = await asyncio.to_thread(self._search_sync, query, limit)
        except Exception:
            return []

        out: list[SourceCandidate] = []
        for r in rows or []:
            try:
                url = r.get("href") or r.get("url") or ""
                title = clean_text(r.get("title")) or url
                if not url:
                    continue
                cand = SourceCandidate(
                    title=title,
                    url=url,
                    provider=self.name,
                    kind="web",
                    abstract=clean_text(r.get("body")) or None,
                    raw=dict(r),
                )
                out.append(cand.normalize())
            except Exception:
                continue
        return out[:limit]

    @staticmethod
    def _search_sync(query: str, limit: int) -> list[dict]:
        from ddgs import DDGS

        return list(DDGS().text(query, max_results=limit) or [])
