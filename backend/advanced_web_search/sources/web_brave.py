"""Brave Search web provider (requires BRAVE_API_KEY).

Defensive throughout: any failure returns [].
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider

_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveProvider(SourceProvider):
    name = "brave"
    kind = "web"
    requires_key = True

    def enabled(self) -> bool:
        return bool(os.getenv("BRAVE_API_KEY"))

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key:
            return []
        q = (query or "").strip()
        if not q:
            return []

        params = {"q": q, "count": limit}
        headers = {
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
        }
        try:
            data = await fetch_json(_SEARCH_URL, params=params, headers=headers)
        except Exception:
            return []
        if not data:
            return []

        results = ((data.get("web") or {}).get("results")) or []
        out: list[SourceCandidate] = []
        for r in results[:limit]:
            try:
                url = r.get("url") or ""
                if not url:
                    continue
                cand = SourceCandidate(
                    title=clean_text(r.get("title")) or url,
                    url=url,
                    provider=self.name,
                    kind="web",
                    abstract=clean_text(r.get("description")) or None,
                    raw=dict(r),
                )
                out.append(cand.normalize())
            except Exception:
                continue
        return out
