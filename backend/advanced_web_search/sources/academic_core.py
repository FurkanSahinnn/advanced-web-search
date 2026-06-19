"""CORE academic provider (requires CORE_API_KEY).

CORE aggregates open-access research papers and frequently exposes a direct
full-text download URL, which we surface as ``pdf_url`` for downstream OA
enrichment. Defensive throughout: any failure returns [].
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider

_SEARCH_URL = "https://api.core.ac.uk/v3/search/works"


class CoreProvider(SourceProvider):
    name = "core"
    kind = "academic"
    requires_key = True

    def enabled(self) -> bool:
        return bool(os.getenv("CORE_API_KEY"))

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        api_key = os.getenv("CORE_API_KEY")
        if not api_key:
            return []
        q = (query or "").strip()
        if not q:
            return []

        params = {"q": q, "limit": limit}
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            data = await fetch_json(_SEARCH_URL, params=params, headers=headers)
        except Exception:
            return []
        if not data:
            return []

        results = data.get("results") or []
        out: list[SourceCandidate] = []
        for r in results[:limit]:
            try:
                cand = self._map(r)
                if cand is not None:
                    out.append(cand)
            except Exception:
                continue
        return out

    def _map(self, r: dict) -> Optional[SourceCandidate]:
        title = clean_text(r.get("title"))

        authors = [
            clean_text(a.get("name"))
            for a in (r.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        authors = [a for a in authors if a]

        year = r.get("yearPublished")
        published_date = str(year) if year else None

        doi = r.get("doi") or None
        if doi:
            doi = (
                str(doi)
                .replace("https://doi.org/", "")
                .replace("http://doi.org/", "")
                .strip()
                or None
            )

        pdf_url = r.get("downloadUrl")
        if not pdf_url:
            for u in r.get("sourceFulltextUrls") or []:
                if u:
                    pdf_url = u
                    break

        venue = clean_text(r.get("publisher")) or None

        url = (
            (f"https://doi.org/{doi}" if doi else None)
            or pdf_url
            or r.get("downloadUrl")
            or ""
        )
        title = title or url
        if not url:
            return None

        cand = SourceCandidate(
            title=title,
            url=url,
            provider=self.name,
            kind="academic",
            authors=authors,
            venue=venue,
            published_date=published_date,
            abstract=clean_text(r.get("abstract")) or None,
            pdf_url=pdf_url,
            doi=doi,
            is_oa=True,
            raw=dict(r),
        )
        return cand.normalize()
