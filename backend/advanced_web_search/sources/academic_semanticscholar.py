"""Semantic Scholar academic provider (keyless; better with SEMANTIC_SCHOLAR_API_KEY)."""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider


class SemanticScholarProvider(SourceProvider):
    name = "semanticscholar"
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
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,abstract,year,authors,venue,citationCount,externalIds,openAccessPdf,url",
        }
        headers = None
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers = {"x-api-key": api_key}

        try:
            data = await fetch_json(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
                headers=headers,
            )
        except Exception:
            return []
        if not data:
            return []

        out: list[SourceCandidate] = []
        for r in (data.get("data") or [])[:limit]:
            try:
                cand = self._map(r)
                if cand is not None:
                    out.append(cand)
            except Exception:
                continue
        return out

    def _map(self, r: dict) -> Optional[SourceCandidate]:
        authors = [
            clean_text(a.get("name"))
            for a in (r.get("authors") or [])
            if a.get("name")
        ]

        ext = r.get("externalIds") or {}
        doi = ext.get("DOI")
        arxiv_id = ext.get("ArXiv")

        oa_pdf = r.get("openAccessPdf") or {}
        pdf_url = oa_pdf.get("url")
        is_oa = bool(pdf_url)

        year = r.get("year")
        published_date = str(year) if year else None

        url = r.get("url") or (f"https://doi.org/{doi}" if doi else "") or pdf_url or ""
        title = clean_text(r.get("title")) or url
        if not url:
            return None

        cand = SourceCandidate(
            title=title,
            url=url,
            provider=self.name,
            kind="academic",
            authors=authors,
            venue=clean_text(r.get("venue")) or None,
            published_date=published_date,
            abstract=clean_text(r.get("abstract")) or None,
            pdf_url=pdf_url,
            doi=doi,
            arxiv_id=arxiv_id,
            cited_by_count=r.get("citationCount"),
            is_oa=is_oa,
            raw=dict(r),
        )
        return cand.normalize()
