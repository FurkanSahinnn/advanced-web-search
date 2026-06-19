"""DOAJ (Directory of Open Access Journals) academic provider (keyless)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider, extract_doi


class DoajProvider(SourceProvider):
    name = "doaj"
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
        from urllib.parse import quote

        url = f"https://doaj.org/api/search/articles/{quote(query, safe='')}"
        try:
            data = await fetch_json(url, params={"pageSize": limit})
        except Exception:
            return []
        if not data:
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
        bib = r.get("bibjson") or {}

        authors = [
            clean_text(a.get("name"))
            for a in (bib.get("author") or [])
            if a.get("name")
        ]

        year = bib.get("year")
        published_date = str(year) if year else None

        doi = None
        for ident in bib.get("identifier") or []:
            if (ident.get("type") or "").lower() == "doi":
                doi = extract_doi(ident.get("id")) or ident.get("id")
                break

        url = ""
        pdf_url = None
        for link in bib.get("link") or []:
            href = link.get("url")
            if not href:
                continue
            content_type = (link.get("content_type") or "").lower()
            link_type = (link.get("type") or "").lower()
            if "pdf" in content_type or "pdf" in link_type:
                pdf_url = href
            if not url and link_type == "fulltext":
                url = href
        if not url:
            url = pdf_url or (f"https://doi.org/{doi}" if doi else "")

        venue = clean_text((bib.get("journal") or {}).get("title")) or None

        title = clean_text(bib.get("title")) or url
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
            abstract=clean_text(bib.get("abstract")) or None,
            pdf_url=pdf_url,
            doi=doi,
            is_oa=True,
            raw=dict(r),
        )
        return cand.normalize()
