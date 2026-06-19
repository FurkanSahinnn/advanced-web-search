"""
Candidate de-duplication.

Cross-provider hits are merged in two passes:

  1) Canonical merge: every candidate is `normalize()`-d (fills canonical_id)
     and grouped by canonical_id. Duplicates within a group are merged into the
     record carrying the most metadata (longer abstract, has DOI, has
     cited_by_count), unioning authors and keeping the strongest numeric/flag
     signals.

  2) Cheap near-duplicate pass: by normalized title (lowercased, punctuation
     stripped). Later duplicate titles are dropped.

Pure and fast: no network, no DB, no model calls.
"""

from __future__ import annotations

import re
from typing import Optional

from ..sources.base import SourceCandidate

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+", re.UNICODE)


def _norm_title(title: Optional[str]) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy title match."""
    if not title:
        return ""
    t = _PUNCT.sub(" ", title.lower())
    t = _WS.sub(" ", t).strip()
    return t


def _metadata_richness(c: SourceCandidate) -> tuple:
    """Sort key: prefer records with more useful metadata. Higher tuple wins."""
    abstract_len = len(c.abstract or "")
    return (
        1 if c.doi else 0,
        1 if c.cited_by_count is not None else 0,
        abstract_len,
        1 if c.full_text else 0,
        1 if c.venue else 0,
        len(c.authors or []),
    )


def _merge_into(base: SourceCandidate, other: SourceCandidate) -> SourceCandidate:
    """Fold `other` into `base` (base is the richer record). Mutates+returns base."""
    # longer abstract wins
    if (len(other.abstract or "")) > (len(base.abstract or "")):
        base.abstract = other.abstract
    # backfill missing scalar metadata
    if not base.full_text and other.full_text:
        base.full_text = other.full_text
    if not base.doi and other.doi:
        base.doi = other.doi
    if not base.arxiv_id and other.arxiv_id:
        base.arxiv_id = other.arxiv_id
    if not base.venue and other.venue:
        base.venue = other.venue
    if not base.venue_quartile and other.venue_quartile:
        base.venue_quartile = other.venue_quartile
    if not base.published_date and other.published_date:
        base.published_date = other.published_date
    if not base.pdf_url and other.pdf_url:
        base.pdf_url = other.pdf_url
    if not base.title and other.title:
        base.title = other.title
    if not base.url and other.url:
        base.url = other.url

    # max cited_by_count
    cb_vals = [v for v in (base.cited_by_count, other.cited_by_count) if v is not None]
    if cb_vals:
        base.cited_by_count = max(cb_vals)

    # keep OA if either is OA
    base.is_oa = bool(base.is_oa or other.is_oa)

    # keep best retrieval hint
    base.retrieval_score = max(base.retrieval_score or 0.0, other.retrieval_score or 0.0)

    # union authors (preserve order, dedup case-insensitively)
    seen = {a.strip().lower() for a in (base.authors or []) if a}
    for a in other.authors or []:
        key = a.strip().lower()
        if a and key not in seen:
            base.authors.append(a)
            seen.add(key)

    return base


def dedup_candidates(cands: list[SourceCandidate]) -> list[SourceCandidate]:
    """Merge cross-provider duplicates and drop near-duplicate titles.

    Pure, defensive: malformed records are skipped rather than raising.
    """
    if not cands:
        return []

    # --- pass 1: canonical merge ---
    groups: dict[str, SourceCandidate] = {}
    order: list[str] = []
    for c in cands:
        if c is None:
            continue
        try:
            c.normalize()
        except Exception:
            # without a canonical_id, fall back to url/title as a weak key
            c.canonical_id = c.canonical_id or f"url:{c.url or _norm_title(c.title) or 'unknown'}"
        cid = c.canonical_id or "url:unknown"
        existing = groups.get(cid)
        if existing is None:
            groups[cid] = c
            order.append(cid)
        else:
            # the richer record becomes base; merge the other into it
            if _metadata_richness(c) > _metadata_richness(existing):
                groups[cid] = _merge_into(c, existing)
            else:
                groups[cid] = _merge_into(existing, c)

    merged = [groups[cid] for cid in order]

    # --- pass 2: near-duplicate title pass ---
    out: list[SourceCandidate] = []
    seen_titles: set[str] = set()
    for c in merged:
        key = _norm_title(c.title)
        if key and key in seen_titles:
            continue
        if key:
            seen_titles.add(key)
        out.append(c)

    return out
