"""arXiv preprint provider (keyless) via the Atom export API + feedparser."""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..utils.http import fetch_text
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider, extract_arxiv_id


class ArxivProvider(SourceProvider):
    name = "arxiv"
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
        from urllib.parse import urlencode

        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        }
        url = "http://export.arxiv.org/api/query?" + urlencode(params)
        try:
            text = await fetch_text(url)
        except Exception:
            return []
        if not text:
            return []

        try:
            import feedparser

            feed = feedparser.parse(text)
        except Exception:
            return []

        out: list[SourceCandidate] = []
        for entry in (getattr(feed, "entries", None) or [])[:limit]:
            try:
                cand = self._map_entry(entry)
                if cand is not None:
                    out.append(cand)
            except Exception:
                continue
        return out

    def _map_entry(self, entry) -> Optional[SourceCandidate]:
        entry_id = entry.get("id") or ""
        arxiv_id = extract_arxiv_id(entry_id)

        authors = [
            clean_text(a.get("name"))
            for a in (entry.get("authors") or [])
            if a.get("name")
        ]

        pdf_url = None
        page_url = entry.get("link") or entry_id
        for link in entry.get("links") or []:
            if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                pdf_url = link.get("href")
            elif link.get("rel") == "alternate" and link.get("href"):
                page_url = link.get("href")

        published = entry.get("published") or entry.get("updated")
        published_date = published[:10] if published else None

        url = page_url or entry_id
        if not url:
            return None

        cand = SourceCandidate(
            title=clean_text(entry.get("title")) or url,
            url=url,
            provider=self.name,
            kind="preprint",
            authors=authors,
            published_date=published_date,
            abstract=clean_text(entry.get("summary")) or None,
            pdf_url=pdf_url,
            arxiv_id=arxiv_id,
            is_oa=True,
            raw=dict(entry),
        )
        return cand.normalize()
