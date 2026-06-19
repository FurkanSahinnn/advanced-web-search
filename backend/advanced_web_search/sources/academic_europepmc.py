"""Europe PMC academic provider (keyless)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider


class EuropePmcProvider(SourceProvider):
    name = "europepmc"
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
            "format": "json",
            "pageSize": limit,
            "resultType": "core",
        }
        try:
            data = await fetch_json(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params=params,
            )
        except Exception:
            return []
        if not data:
            return []

        results = (data.get("resultList") or {}).get("result") or []
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
        doi = r.get("doi")
        authors = [
            a.strip()
            for a in (r.get("authorString") or "").replace(".", "").split(",")
            if a.strip()
        ]

        pub_year = r.get("pubYear")
        published_date = str(pub_year) if pub_year else None

        venue = (
            ((r.get("journalInfo") or {}).get("journal") or {}).get("title")
        )

        pdf_url = None
        for ft in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
            doc_style = (ft.get("documentStyle") or "").lower()
            if doc_style == "pdf" and ft.get("url"):
                pdf_url = ft.get("url")
                break
        if pdf_url is None:
            for ft in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
                if ft.get("url"):
                    pdf_url = ft.get("url")
                    break

        url = (
            (f"https://doi.org/{doi}" if doi else None)
            or (pdf_url)
            or (
                f"https://europepmc.org/abstract/{r.get('source')}/{r.get('id')}"
                if r.get("source") and r.get("id")
                else ""
            )
        )
        title = clean_text(r.get("title")) or url
        if not url:
            return None

        cand = SourceCandidate(
            title=title,
            url=url,
            provider=self.name,
            kind="academic",
            authors=authors,
            venue=clean_text(venue) or None,
            published_date=published_date,
            abstract=clean_text(r.get("abstractText")) or None,
            pdf_url=pdf_url,
            doi=doi,
            cited_by_count=r.get("citedByCount"),
            is_oa=(r.get("isOpenAccess") == "Y"),
            raw=dict(r),
        )
        return cand.normalize()
