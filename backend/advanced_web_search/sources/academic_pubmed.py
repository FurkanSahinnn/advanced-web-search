"""PubMed academic provider (keyless NCBI E-utilities).

Two-step lookup: esearch -> id list, then esummary -> per-article metadata.
Polite ``tool``/``email`` params are added when a contact email is configured.
Defensive throughout: any failure returns [].
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..config import get_settings
from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate, SourceProvider

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


class PubMedProvider(SourceProvider):
    name = "pubmed"
    kind = "academic"
    requires_key = False

    def enabled(self) -> bool:
        return True

    def _politeness(self) -> dict:
        params: dict = {"tool": "advanced-web-search"}
        email = get_settings().contact_email
        if email:
            params["email"] = email
        return params

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        q = (query or "").strip()
        if not q:
            return []

        search_params = {
            "db": "pubmed",
            "term": q,
            "retmax": limit,
            "retmode": "json",
            **self._politeness(),
        }
        try:
            sdata = await fetch_json(_ESEARCH, params=search_params)
        except Exception:
            return []
        if not sdata:
            return []

        try:
            ids = ((sdata.get("esearchresult") or {}).get("idlist")) or []
        except Exception:
            ids = []
        ids = [str(i) for i in ids if str(i).strip()][:limit]
        if not ids:
            return []

        summary_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            **self._politeness(),
        }
        try:
            data = await fetch_json(_ESUMMARY, params=summary_params)
        except Exception:
            return []
        if not data:
            return []

        result = data.get("result") or {}
        out: list[SourceCandidate] = []
        for uid in ids:
            r = result.get(uid)
            if not isinstance(r, dict):
                continue
            try:
                cand = self._map(uid, r)
                if cand is not None:
                    out.append(cand)
            except Exception:
                continue
        return out

    def _map(self, uid: str, r: dict) -> Optional[SourceCandidate]:
        title = clean_text(r.get("title"))

        authors = [
            clean_text(a.get("name"))
            for a in (r.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        authors = [a for a in authors if a]

        venue = clean_text(r.get("source") or r.get("fulljournalname")) or None

        pubdate = r.get("pubdate") or r.get("epubdate") or ""
        year = None
        if pubdate:
            head = str(pubdate).strip().split(" ")[0]
            if head[:4].isdigit():
                year = head[:4]

        doi = None
        for aid in r.get("articleids") or []:
            if isinstance(aid, dict) and (aid.get("idtype") or "").lower() == "doi":
                val = (aid.get("value") or "").strip()
                if val:
                    doi = val
                    break

        url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
        title = title or url

        cand = SourceCandidate(
            title=title,
            url=url,
            provider=self.name,
            kind="academic",
            authors=authors,
            venue=venue,
            published_date=year,
            doi=doi,
            raw=dict(r),
        )
        return cand.normalize()
