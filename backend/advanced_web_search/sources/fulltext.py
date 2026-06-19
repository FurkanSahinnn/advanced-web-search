"""Best-effort open-access full-text retrieval for academic candidates.

Two public helpers:

  * ``extract_pdf_text(data)``   — pull text out of PDF bytes via pypdf.
  * ``resolve_fulltext(cand)``   — given ONE candidate dict, try the cheapest
    open-access route to real full text (Europe PMC OA fulltext, Unpaywall PDF,
    the candidate's own pdf_url, or finally the landing page HTML).

Everything here is defensive: any failure returns "" / None, never raises. The
researcher node uses this to enrich a few top academic sources before indexing,
so chunks + synthesizer grounding + verifier stance see real full text.
"""

from __future__ import annotations

import io
from typing import Optional

from ..utils.http import fetch_bytes, fetch_text
from ..utils.text import clean_text, extract_main_text, truncate
from . import academic_unpaywall as unpaywall


def extract_pdf_text(data: bytes, *, max_chars: int = 20000) -> str:
    """Extract text from PDF bytes using pypdf. Resilient -> "" on any failure."""
    if not data:
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                continue
            if txt:
                parts.append(txt)
                total += len(txt)
                if total >= max_chars * 2:  # plenty; stop early on huge PDFs
                    break
        joined = clean_text("\n\n".join(parts))
        if not joined:
            return ""
        return truncate(joined, max_chars)
    except Exception:
        return ""


def _europepmc_oa_url(raw: dict) -> Optional[str]:
    """Find an OA full-text (XML/HTML) URL from a Europe PMC raw record."""
    if not isinstance(raw, dict):
        return None
    ft_list = (raw.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    # Prefer an explicitly open / full-text document (html or xml) over pdf here;
    # PDFs are handled by the pdf_url branch.
    candidates: list[str] = []
    for ft in ft_list:
        if not isinstance(ft, dict):
            continue
        url = ft.get("url")
        if not url:
            continue
        style = (ft.get("documentStyle") or "").lower()
        availability = (ft.get("availability") or "").lower()
        if style in ("html", "xml") and ("open" in availability or "free" in availability or not availability):
            candidates.append(url)
    if candidates:
        return candidates[0]

    # Fall back to constructing an OA fulltext endpoint from a PMCID.
    pmcid = raw.get("pmcid")
    if pmcid:
        pmcid = str(pmcid).strip()
        if pmcid:
            return (
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/"
                "fullTextXML"
            )
    return None


async def resolve_fulltext(cand: dict, *, max_chars: int = 8000) -> Optional[str]:
    """Best-effort OA full text for ONE academic candidate dict. Never raises.

    Resolution order:
      (a) Europe PMC OA full text (pmcid / fullTextUrlList) -> XML/HTML -> text
      (b) DOI -> unpaywall.lookup_oa -> pdf_url -> fetch_bytes -> extract_pdf_text
      (c) cand['pdf_url'] -> fetch_bytes -> extract_pdf_text
      (d) fetch_text(url) -> extract_main_text

    Returns truncated text, or None if nothing usable was retrieved.
    """
    if not isinstance(cand, dict):
        return None

    raw = cand.get("raw") if isinstance(cand.get("raw"), dict) else {}
    doi = cand.get("doi")
    pdf_url = cand.get("pdf_url")
    url = cand.get("url")

    # (a) Europe PMC open-access full text (XML/HTML).
    try:
        oa_url = _europepmc_oa_url(raw)
    except Exception:
        oa_url = None
    if oa_url:
        try:
            html = await fetch_text(oa_url)
            if html:
                txt = extract_main_text(html, oa_url)
                if txt and len(txt) > 200:
                    return truncate(txt, max_chars)
        except Exception:
            pass

    # (b) DOI -> Unpaywall -> PDF.
    if doi:
        try:
            oa = await unpaywall.lookup_oa(doi)
        except Exception:
            oa = None
        oa_pdf = (oa or {}).get("pdf_url") if isinstance(oa, dict) else None
        if oa_pdf:
            try:
                data = await fetch_bytes(oa_pdf)
                if data:
                    txt = extract_pdf_text(data)
                    if txt and len(txt) > 200:
                        return truncate(txt, max_chars)
            except Exception:
                pass

    # (c) Candidate's own PDF url.
    if pdf_url:
        try:
            data = await fetch_bytes(pdf_url)
            if data:
                txt = extract_pdf_text(data)
                if txt and len(txt) > 200:
                    return truncate(txt, max_chars)
        except Exception:
            pass

    # (d) Landing-page HTML.
    if url:
        try:
            html = await fetch_text(url)
            if html:
                txt = extract_main_text(html, url)
                if txt and len(txt) > 200:
                    return truncate(txt, max_chars)
        except Exception:
            pass

    return None
