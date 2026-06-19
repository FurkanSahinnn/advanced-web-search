"""Unpaywall enricher (keyless).

Unpaywall is an enricher, not a search engine: `search()` always returns [].
The module-level `lookup_oa(doi)` helper resolves open-access status + a best
PDF url for a known DOI.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..config import get_settings
from ..utils.http import fetch_json
from .base import SourceCandidate, SourceProvider


class UnpaywallProvider(SourceProvider):
    name = "unpaywall"
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
        # Enricher only: not a discovery source.
        return []


async def lookup_oa(doi: str) -> Optional[dict]:
    """Resolve open-access status + best PDF url for a DOI. Returns None on failure."""
    if not doi:
        return None
    email = get_settings().contact_email or "advanced-web-search@example.com"
    try:
        data = await fetch_json(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
        )
    except Exception:
        return None
    if not data:
        return None

    try:
        best = data.get("best_oa_location") or {}
        return {
            "is_oa": bool(data.get("is_oa")),
            "pdf_url": best.get("url_for_pdf") or best.get("url"),
        }
    except Exception:
        return None
