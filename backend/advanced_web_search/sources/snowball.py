"""
Citation snowballing over OpenAlex.

Given a set of already-kept academic sources (seeds), expand the evidence base
by following the citation graph in BOTH directions:

  * backward — the works each seed *references* (``referenced_works``)
  * forward  — the works that *cite* each seed (``filter=cites:<id>``)

Each discovered work is mapped to a :class:`SourceCandidate`
(``provider='openalex-snowball'``) so it can flow through the normal dedup /
index / score pipeline like any other source.

Everything here is best-effort and bounded: any failure resolving a seed or
fetching a page degrades to fewer (or zero) candidates — it never raises.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from ..config import get_settings
from ..utils.http import fetch_json
from ..utils.text import clean_text
from .base import SourceCandidate

_OPENALEX_BASE = "https://api.openalex.org/works"

# Hard safety caps so a pathological seed set can never blow up the run.
_MAX_SEEDS = 25
_MAX_REF_IDS_PER_SEED = 25
_BATCH_SIZE = 25  # OpenAlex `openalex_id:a|b|c` filter batch size


def _params(extra: dict | None = None) -> dict:
    """Base query params mirroring academic_openalex.py (mailto + api_key)."""
    params: dict[str, Any] = {}
    try:
        email = get_settings().contact_email
        if email:
            params["mailto"] = email
    except Exception:
        pass
    api_key = os.getenv("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    if extra:
        params.update(extra)
    return params


def _short_id(openalex_id: Optional[str]) -> Optional[str]:
    """Reduce a full OpenAlex work URL to its bare id (e.g. 'W2741809807')."""
    if not openalex_id:
        return None
    sid = str(openalex_id).rstrip("/").rsplit("/", 1)[-1]
    return sid or None


def _map_work(r: dict) -> Optional[SourceCandidate]:
    """Map an OpenAlex work JSON object to a normalized SourceCandidate."""
    try:
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
            provider="openalex-snowball",
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
    except Exception:
        return None


async def _resolve_work(seed: dict) -> Optional[dict]:
    """Resolve a seed source row to an OpenAlex work JSON object."""
    provider = (seed.get("provider") or "").lower()
    raw = seed.get("raw")

    # 1) Native OpenAlex seed — parse the stored raw JSON for the work object/id.
    if provider in ("openalex", "openalex-snowball") and raw:
        try:
            import json

            obj = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            obj = None
        if isinstance(obj, dict):
            # If the stored raw already looks like a full work, use it directly.
            if obj.get("id") and obj.get("display_name"):
                return obj
            oid = _short_id(obj.get("id"))
            if oid:
                data = await fetch_json(f"{_OPENALEX_BASE}/{oid}", params=_params())
                if isinstance(data, dict):
                    return data

    # 2) DOI-based resolution via canonical_id (doi:...).
    cid = seed.get("canonical_id") or ""
    if isinstance(cid, str) and cid.startswith("doi:"):
        doi = cid[len("doi:"):].strip()
        if doi:
            data = await fetch_json(f"{_OPENALEX_BASE}/doi:{doi}", params=_params())
            if isinstance(data, dict):
                return data

    return None


async def _fetch_referenced(ids: list[str], total_budget: int) -> list[SourceCandidate]:
    """Batch-fetch referenced works via the openalex_id OR-filter."""
    out: list[SourceCandidate] = []
    if not ids:
        return out
    # de-dup + cap the id universe
    seen: set[str] = set()
    uniq: list[str] = []
    for i in ids:
        s = _short_id(i)
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)

    for start in range(0, len(uniq), _BATCH_SIZE):
        if len(out) >= total_budget:
            break
        batch = uniq[start:start + _BATCH_SIZE]
        flt = "openalex_id:" + "|".join(batch)
        try:
            data = await fetch_json(
                _OPENALEX_BASE,
                params=_params({"filter": flt, "per_page": len(batch)}),
            )
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for r in (data.get("results") or []):
            cand = _map_work(r)
            if cand is not None:
                out.append(cand)
            if len(out) >= total_budget:
                break
    return out


async def _fetch_citing(openalex_id: str, per_seed: int, total_budget: int) -> list[SourceCandidate]:
    """Fetch works that cite a given OpenAlex work."""
    out: list[SourceCandidate] = []
    oid = _short_id(openalex_id)
    if not oid:
        return out
    try:
        data = await fetch_json(
            _OPENALEX_BASE,
            params=_params({"filter": f"cites:{oid}", "per_page": max(1, int(per_seed))}),
        )
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for r in (data.get("results") or []):
        if len(out) >= total_budget:
            break
        cand = _map_work(r)
        if cand is not None:
            out.append(cand)
    return out


async def expand_citations(
    seeds: list[dict],
    *,
    per_seed: int = 8,
    total_limit: int = 60,
) -> list[SourceCandidate]:
    """Expand a seed set of academic sources along the citation graph.

    Returns up to ``total_limit`` normalized SourceCandidate objects discovered
    via referenced + citing works. Resilient: returns ``[]`` on any failure and
    never raises to the caller.
    """
    try:
        if not seeds:
            return []
        seeds = list(seeds)[:_MAX_SEEDS]
        collected: list[SourceCandidate] = []

        for seed in seeds:
            if len(collected) >= total_limit:
                break
            if not isinstance(seed, dict):
                continue
            try:
                work = await _resolve_work(seed)
            except Exception:
                work = None
            if not isinstance(work, dict):
                continue

            oid = _short_id(work.get("id"))

            # backward: referenced works (capped per seed)
            ref_ids = work.get("referenced_works") or []
            if isinstance(ref_ids, list) and ref_ids:
                remaining = total_limit - len(collected)
                if remaining > 0:
                    refs = await _fetch_referenced(
                        ref_ids[:_MAX_REF_IDS_PER_SEED], remaining
                    )
                    collected.extend(refs)

            # forward: citing works
            if oid and len(collected) < total_limit:
                remaining = total_limit - len(collected)
                citing = await _fetch_citing(oid, per_seed, remaining)
                collected.extend(citing)

        return collected[:total_limit]
    except Exception:
        return []
