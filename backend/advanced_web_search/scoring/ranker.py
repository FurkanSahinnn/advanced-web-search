"""
Multi-signal source ranker.

For each candidate source we compute five components in [0, 1]:

    relevance        cross-encoder rerank of (title + abstract) vs the query,
                     min-max normalized across the batch (dominant signal).
    authority        venue quartile (academic) or domain-trust (web).
    recency          exponential decay from the publish date (3y half-life).
    citation_impact  log-normalized citation count.
    evidence         evidence-type score (meta-analysis ... blog), EN+TR aware.

`final_score` is the weight-normalized dot product of the five components.
`match_score` is `round(final_score * 100)`. A source is `kept` when
`final_score >= keep_threshold`. `why_kept` is a short bilingual-safe chip
summarizing the two strongest signals.

Returns `[{"source_id": id, "breakdown": {...ScoreBreakdown fields...}}]`. The
ranker never persists and never raises to the caller — on any failure a source
gets a neutral breakdown so the pipeline can proceed.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from ..embeddings import reranker

log = logging.getLogger("advanced_web_search.ranker")

# --------------------------------------------------------------------------- #
# Domain-trust tables (host -> authority score)
# --------------------------------------------------------------------------- #

_REPUTABLE_HOSTS = {
    "nature.com": 0.8, "science.org": 0.8, "who.int": 0.8, "oecd.org": 0.8,
    "nih.gov": 0.8, "reuters.com": 0.8, "apnews.com": 0.8, "economist.com": 0.8,
    "ft.com": 0.8, "mit.edu": 0.8, "stanford.edu": 0.8, "arxiv.org": 0.8,
    "acm.org": 0.8, "ieee.org": 0.8,
}
# substrings that mark obvious low-trust blog/self-publish platforms
_LOW_TRUST_MARKERS = ("medium.com", "blogspot", "wordpress.com", "substack.com")

# hosts treated as reputable news for the evidence signal
_REPUTABLE_NEWS_HOSTS = (
    "reuters.com", "apnews.com", "economist.com", "ft.com", "bbc.co.uk",
    "bbc.com", "nytimes.com", "washingtonpost.com", "theguardian.com",
    "wsj.com", "bloomberg.com", "aljazeera.com", "dw.com",
)

_QUARTILE_SCORE = {"Q1": 1.0, "Q2": 0.8, "Q3": 0.6, "Q4": 0.4}

# evidence_type -> score (per spec)
_EVIDENCE_SCORE = {
    "meta_analysis": 1.0,
    "systematic_review": 0.95,
    "rct": 0.9,
    "peer_reviewed": 0.75,
    "preprint": 0.55,
    "reputable_news": 0.45,
    "blog": 0.3,
    "dataset": 0.5,
    "unknown": 0.3,
}

_HALF_LIFE_YEARS = 3.0

# Cross-encoder relevance is reranked over the source TEXT, not just its title +
# abstract: when a source has fetched body text, a leading slice is appended so a
# source with a generic abstract but a strongly on-topic body is not under-scored
# (the abstract-only doc was the granularity mismatch). Capped to stay within a
# typical cross-encoder's input window.
_RERANK_BODY_CHARS = 800

# Adaptive top-k (score-gap / "elbow" cut). After the fixed keep_threshold has
# decided the kept set, if that set has a clear quality cliff we drop the long
# tail below it — so an easy sub-question keeps a few strong sources and a broad
# one keeps more, without a second tuning knob. Guard rails keep it conservative:
# never cut below MIN_KEEP survivors, and only cut on a genuinely large gap.
_ADAPTIVE_MIN_KEEP = 4
_ADAPTIVE_GAP_RATIO = 1.8   # the cut gap must be this much bigger than the mean gap
_ADAPTIVE_GAP_ABS = 0.08    # ...and at least this large in absolute final_score


def _apply_adaptive_cut(results: list[dict], threshold: float) -> None:
    """Demote the weak tail of the kept set in place when there's a clear elbow.

    Operates only on sources already kept by ``threshold`` (the hard floor), so
    this can only ever tighten, never resurrect a below-threshold source. Sets
    ``kept=False`` on the demoted tail. Fully defensive: any anomaly leaves the
    threshold decision untouched.
    """
    try:
        kept = [r for r in results if (r.get("breakdown") or {}).get("kept")]
        if len(kept) <= _ADAPTIVE_MIN_KEEP:
            return
        kept.sort(key=lambda r: float(r["breakdown"].get("final_score") or 0.0), reverse=True)
        scores = [float(r["breakdown"].get("final_score") or 0.0) for r in kept]
        gaps = [scores[i] - scores[i + 1] for i in range(len(scores) - 1)]
        if not gaps:
            return
        mean_gap = sum(gaps) / len(gaps)
        # Only consider cut points AFTER the first MIN_KEEP survivors so we always
        # keep at least that many.
        best_i, best_gap = -1, 0.0
        for i in range(_ADAPTIVE_MIN_KEEP - 1, len(gaps)):
            if gaps[i] > best_gap:
                best_gap, best_i = gaps[i], i
        if best_i < 0:
            return
        if best_gap >= _ADAPTIVE_GAP_ABS and best_gap >= _ADAPTIVE_GAP_RATIO * max(mean_gap, 1e-9):
            for r in kept[best_i + 1:]:
                r["breakdown"]["kept"] = False
    except Exception:
        return


def _host_of(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        host = (urlsplit(url).hostname or "").lower()
        return host.removeprefix("www.")
    except Exception:
        return ""


def _is_academic_kind(kind: Optional[str]) -> bool:
    return (kind or "").lower() in ("academic", "preprint")


# --------------------------------------------------------------------------- #
# Component scorers
# --------------------------------------------------------------------------- #

def _authority(src: dict) -> float:
    kind = src.get("kind")
    url = src.get("url")
    host = _host_of(url)

    if _is_academic_kind(kind):
        quartile = (src.get("venue_quartile") or "").upper()
        if quartile in _QUARTILE_SCORE:
            return _QUARTILE_SCORE[quartile]
        return 0.6 if src.get("venue") else 0.5

    # web domain-trust
    if not host:
        return 0.5
    if host.endswith(".gov") or host.endswith(".edu") or ".ac." in f".{host}":
        return 0.9
    if host in _REPUTABLE_HOSTS:
        return _REPUTABLE_HOSTS[host]
    # allow subdomains of reputable hosts
    for h, score in _REPUTABLE_HOSTS.items():
        if host == h or host.endswith("." + h):
            return score
    if any(marker in host for marker in _LOW_TRUST_MARKERS):
        return 0.3
    return 0.5


def _parse_year_fraction(date_str: Optional[str]) -> Optional[float]:
    """Parse an ISO date (YYYY or YYYY-MM-DD) into a float year (e.g. 2024.46)."""
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(s[: len(fmt) + (2 if "%d" in fmt else 0)], fmt)
            day_of_year = dt.timetuple().tm_yday
            return dt.year + (day_of_year - 1) / 365.25
        except Exception:
            continue
    # last resort: leading 4-digit year
    m = re.match(r"\s*(\d{4})", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _recency(src: dict) -> float:
    year_frac = _parse_year_fraction(src.get("published_date"))
    if year_frac is None:
        return 0.4
    now = datetime.now(timezone.utc)
    now_frac = now.year + (now.timetuple().tm_yday - 1) / 365.25
    age = now_frac - year_frac
    if age < 0:
        age = 0.0
    try:
        score = 0.5 ** (age / _HALF_LIFE_YEARS)
    except Exception:
        return 0.4
    return max(0.0, min(1.0, score))


def _citation_impact(src: dict) -> float:
    cites = src.get("cited_by_count")
    kind = src.get("kind")
    if cites is None or not _is_academic_kind(kind):
        # web / no cites
        if cites is None:
            return 0.2
    try:
        n = int(cites) if cites is not None else 0
    except Exception:
        n = 0
    if n <= 0:
        return 0.2 if not _is_academic_kind(kind) else 0.0
    return min(1.0, math.log10(1 + n) / 4.0)


def _detect_evidence_type(src: dict) -> str:
    """Detect evidence_type from title+venue+provider keywords (EN + TR)."""
    title = (src.get("title") or "").lower()
    venue = (src.get("venue") or "").lower()
    provider = (src.get("provider") or "").lower()
    kind = (src.get("kind") or "").lower()
    blob = f"{title} {venue} {provider}"
    host = _host_of(src.get("url"))

    if "meta-analysis" in blob or "meta analysis" in blob or "meta analiz" in blob:
        return "meta_analysis"
    if "systematic review" in blob or "sistematik derleme" in blob:
        return "systematic_review"
    if any(kw in blob for kw in ("randomized", "randomised", "randomize", " rct", "rct ")) \
            or blob.strip().endswith("rct") or "randomize" in blob:
        return "rct"

    # preprint detection
    is_preprint = (
        kind == "preprint"
        or "arxiv" in provider or "biorxiv" in provider or "medrxiv" in provider
        or "preprint" in blob
        or host in ("arxiv.org", "biorxiv.org", "medrxiv.org")
    )
    if is_preprint:
        return "preprint"

    # peer-reviewed academic with a named venue
    if _is_academic_kind(kind) and src.get("venue"):
        return "peer_reviewed"

    # reputable news host
    if host and (host in _REPUTABLE_NEWS_HOSTS
                 or any(host == h or host.endswith("." + h) for h in _REPUTABLE_NEWS_HOSTS)):
        return "reputable_news"

    return "blog"


def _evidence(src: dict) -> tuple[float, str]:
    etype = _detect_evidence_type(src)
    return _EVIDENCE_SCORE.get(etype, 0.3), etype


def _normalize_weights(weights: Optional[dict]) -> dict:
    keys = ("relevance", "authority", "recency", "citation_impact", "evidence")
    w = {}
    for k in keys:
        try:
            w[k] = max(0.0, float((weights or {}).get(k, 0.0)))
        except Exception:
            w[k] = 0.0
    total = sum(w.values())
    if total <= 0:
        # fall back to the project default split
        return {"relevance": 0.40, "authority": 0.15, "recency": 0.15,
                "citation_impact": 0.15, "evidence": 0.15}
    return {k: v / total for k, v in w.items()}


def _min_max_normalize(raw: list[float]) -> list[float]:
    """Min-max into [0,1]; if all equal (or empty handled by caller) -> 0.6."""
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    if hi - lo < 1e-9:
        return [0.6 for _ in raw]
    return [(x - lo) / (hi - lo) for x in raw]


# --------------------------------------------------------------------------- #
# why_kept chip
# --------------------------------------------------------------------------- #

def _why_kept(src: dict, comps: dict, etype: str) -> str:
    """Short bilingual-safe chip summarizing the 2 strongest signals."""
    chips: list[tuple[float, str]] = []

    # relevance
    chips.append((comps["relevance"], "yüksek ilgi" if comps["relevance"] >= 0.66 else "orta ilgi"))

    # authority
    quartile = (src.get("venue_quartile") or "").upper()
    if quartile in _QUARTILE_SCORE:
        chips.append((comps["authority"], f"{quartile} dergi"))
    elif comps["authority"] >= 0.8:
        chips.append((comps["authority"], "güvenilir kaynak"))

    # recency -> show year
    year_frac = _parse_year_fraction(src.get("published_date"))
    if year_frac is not None:
        chips.append((comps["recency"], str(int(year_frac))))

    # citations
    cites = src.get("cited_by_count")
    try:
        n = int(cites) if cites is not None else 0
    except Exception:
        n = 0
    if n > 0:
        chips.append((comps["citation_impact"], f"{n} atıf"))

    # evidence type chip for strong evidence
    strong_evidence = {
        "meta_analysis": "meta-analiz",
        "systematic_review": "sistematik derleme",
        "rct": "RKÇ",
        "peer_reviewed": "hakemli",
    }
    if etype in strong_evidence:
        chips.append((comps["evidence"], strong_evidence[etype]))

    # pick the 2 strongest distinct labels (preserve their natural phrasing)
    chips.sort(key=lambda c: c[0], reverse=True)
    labels: list[str] = []
    for _, label in chips:
        if label not in labels:
            labels.append(label)
        if len(labels) >= 2:
            break
    return " · ".join(labels)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

async def score_sources(
    query: str,
    sources: list[dict],
    weights: dict,
    keep_threshold: float,
) -> list[dict]:
    """Score sources on five signals and return per-source ScoreBreakdown dicts.

    Never raises: any failure yields a neutral breakdown for that source.
    """
    if not sources:
        return []

    norm_w = _normalize_weights(weights)
    try:
        threshold = float(keep_threshold)
    except Exception:
        threshold = 0.45

    # --- relevance via cross-encoder (batch) ---
    docs: list[str] = []
    for s in sources:
        title = (s.get("title") or "").strip()
        abstract = (s.get("abstract") or "").strip()
        doc = f"{title}. {abstract}".strip()
        body = (s.get("full_text") or "").strip()
        if body:
            # Append a leading slice of the actual body so the reranker sees the
            # source's content, not just its (possibly generic) abstract.
            doc = f"{doc}\n{body[:_RERANK_BODY_CHARS]}".strip()
        docs.append(doc)

    try:
        raw_scores = await reranker.arerank(query or "", docs)
    except Exception as exc:
        log.warning("rerank failed in score_sources: %s", exc)
        raw_scores = []
    if len(raw_scores) != len(sources):
        # degrade: neutral relevance everywhere
        relevances = [0.6 for _ in sources]
    else:
        relevances = _min_max_normalize([float(x) for x in raw_scores])
        if not relevances:
            relevances = [0.6 for _ in sources]

    results: list[dict] = []
    for src, relevance in zip(sources, relevances):
        try:
            authority = _authority(src)
            recency = _recency(src)
            citation_impact = _citation_impact(src)
            evidence, evidence_type = _evidence(src)

            comps = {
                "relevance": float(relevance),
                "authority": float(authority),
                "recency": float(recency),
                "citation_impact": float(citation_impact),
                "evidence": float(evidence),
            }

            final_score = sum(norm_w[k] * comps[k] for k in comps)
            final_score = max(0.0, min(1.0, final_score))
            match_score = int(round(final_score * 100))
            kept = final_score >= threshold
            why = _why_kept(src, comps, evidence_type)

            detail = {
                "relevance": round(comps["relevance"], 4),
                "authority": round(comps["authority"], 4),
                "recency": round(comps["recency"], 4),
                "citation_impact": round(comps["citation_impact"], 4),
                "evidence": round(comps["evidence"], 4),
                "evidence_type": evidence_type,
                "weights": {k: round(v, 4) for k, v in norm_w.items()},
            }

            breakdown = {
                "relevance": comps["relevance"],
                "authority": comps["authority"],
                "recency": comps["recency"],
                "citation_impact": comps["citation_impact"],
                "evidence": comps["evidence"],
                "final_score": round(final_score, 6),
                "match_score": match_score,
                "evidence_type": evidence_type,
                "kept": bool(kept),
                "why_kept": why,
                "supporting_quote": "",
                "detail": detail,
            }
        except Exception as exc:
            log.warning("scoring source %s failed; neutral breakdown: %s", src.get("id"), exc)
            breakdown = {
                "relevance": float(relevance) if isinstance(relevance, (int, float)) else 0.6,
                "authority": 0.5, "recency": 0.4, "citation_impact": 0.2, "evidence": 0.3,
                "final_score": 0.0, "match_score": 0, "evidence_type": "unknown",
                "kept": False, "why_kept": "", "supporting_quote": "", "detail": {},
            }

        results.append({"source_id": src.get("id"), "breakdown": breakdown})

    # Adaptive top-k: tighten the kept set when it has a clear quality cliff.
    _apply_adaptive_cut(results, threshold)

    return results
