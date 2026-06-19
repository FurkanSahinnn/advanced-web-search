"""Tavily web search provider (requires TAVILY_API_KEY)."""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from ..config import get_settings
from ..utils.http import get_client
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider


class TavilyProvider(SourceProvider):
    name = "tavily"
    kind = "web"
    requires_key = True

    def enabled(self) -> bool:
        return get_settings().has_tavily

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return []

        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": limit,
            "search_depth": "advanced",
        }
        try:
            client = await get_client()
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        if not data:
            return []

        out: list[SourceCandidate] = []
        for r in (data.get("results") or [])[:limit]:
            try:
                url = r.get("url") or ""
                if not url:
                    continue
                cand = SourceCandidate(
                    title=clean_text(r.get("title")) or url,
                    url=url,
                    provider=self.name,
                    kind="web",
                    abstract=clean_text(r.get("content")) or None,
                    raw=dict(r),
                )
                out.append(cand.normalize())
            except Exception:
                continue
        return out
