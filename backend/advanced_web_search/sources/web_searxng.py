"""SearXNG web search provider (keyless; enabled when a SearXNG URL is set)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..config import get_settings
from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider


class SearxngProvider(SourceProvider):
    name = "searxng"
    kind = "web"
    requires_key = False

    def enabled(self) -> bool:
        return bool(get_settings().searxng_url)

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        base = get_settings().searxng_url
        if not base:
            return []
        params = {
            "q": query,
            "format": "json",
            "categories": "general,science",
        }
        if language:
            params["language"] = language

        try:
            data = await fetch_json(f"{base.rstrip('/')}/search", params=params)
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
                    published_date=r.get("publishedDate") or None,
                    raw=dict(r),
                )
                out.append(cand.normalize())
            except Exception:
                continue
        return out
