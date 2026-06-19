"""Crossref academic provider (keyless; polite pool when contact_email set)."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..config import get_settings
from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider

_JATS_TAG = re.compile(r"<[^>]+>")


def _strip_jats(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return clean_text(_JATS_TAG.sub(" ", text)) or None


class CrossrefProvider(SourceProvider):
    name = "crossref"
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
            "rows": limit,
            "select": "DOI,title,author,container-title,issued,abstract,is-referenced-by-count,URL",
        }
        email = get_settings().contact_email
        if email:
            params["mailto"] = email

        try:
            data = await fetch_json("https://api.crossref.org/works", params=params)
        except Exception:
            return []
        if not data:
            return []

        items = (data.get("message") or {}).get("items") or []
        out: list[SourceCandidate] = []
        for it in items[:limit]:
            try:
                cand = self._map(it)
                if cand is not None:
                    out.append(cand)
            except Exception:
                continue
        return out

    def _map(self, it: dict) -> Optional[SourceCandidate]:
        doi = it.get("DOI")
        titles = it.get("title") or []
        title = clean_text(titles[0]) if titles else None

        authors: list[str] = []
        for a in it.get("author") or []:
            name = " ".join(
                p for p in (a.get("given"), a.get("family")) if p
            ).strip()
            if name:
                authors.append(name)

        containers = it.get("container-title") or []
        venue = clean_text(containers[0]) if containers else None

        published_date = self._date_from_issued(it.get("issued"))

        url = it.get("URL") or (f"https://doi.org/{doi}" if doi else "")
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
            abstract=_strip_jats(it.get("abstract")),
            doi=doi,
            cited_by_count=it.get("is-referenced-by-count"),
            raw=dict(it),
        )
        return cand.normalize()

    @staticmethod
    def _date_from_issued(issued: Optional[dict]) -> Optional[str]:
        if not issued:
            return None
        parts = (issued.get("date-parts") or [[]])[0]
        if not parts:
            return None
        y = parts[0]
        if y is None:
            return None
        if len(parts) >= 3 and parts[1] and parts[2]:
            return f"{int(y):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        if len(parts) >= 2 and parts[1]:
            return f"{int(y):04d}-{int(parts[1]):02d}"
        return f"{int(y):04d}"
