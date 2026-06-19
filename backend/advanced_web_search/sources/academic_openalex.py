"""OpenAlex academic provider (keyless; uses OPENALEX_API_KEY if present)."""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from ..config import get_settings
from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider


class OpenAlexProvider(SourceProvider):
    name = "openalex"
    kind = "academic"
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
        params = {"search": query, "per_page": limit}
        email = get_settings().contact_email
        if email:
            params["mailto"] = email
        api_key = os.getenv("OPENALEX_API_KEY")
        if api_key:
            params["api_key"] = api_key

        try:
            data = await fetch_json("https://api.openalex.org/works", params=params)
        except Exception:
            return []
        if data is None:
            return []

        out: list[SourceCandidate] = []
        for r in (data.get("results") or [])[:limit]:
            try:
                cand = self._map(r)
                if cand is not None:
                    out.append(cand)
            except Exception:
                continue
        return out

    def _map(self, r: dict) -> Optional[SourceCandidate]:
        title = clean_text(r.get("display_name"))

        doi_raw = r.get("doi")
        doi = None
        if doi_raw:
            doi = doi_raw.replace("https://doi.org/", "").replace("http://doi.org/", "")

        authors = [
            clean_text((a.get("author") or {}).get("display_name"))
            for a in (r.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ]

        primary = r.get("primary_location") or {}
        venue = clean_text((primary.get("source") or {}).get("display_name")) or None
        pdf_url = primary.get("pdf_url")

        open_access = r.get("open_access") or {}
        is_oa = bool(open_access.get("is_oa"))

        url = (
            r.get("id")
            or (f"https://doi.org/{doi}" if doi else None)
            or pdf_url
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
            published_date=r.get("publication_date") or None,
            pdf_url=pdf_url,
            doi=doi,
            cited_by_count=r.get("cited_by_count"),
            is_oa=is_oa,
            raw=dict(r),
        )
        return cand.normalize()
