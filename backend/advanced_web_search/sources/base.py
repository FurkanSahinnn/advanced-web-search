"""
Source provider contract.

Every web/academic connector implements `SourceProvider`. The graph's
researcher node fans out across all enabled providers, merges their
`SourceCandidate` results, then canonicalizes + dedups them
(see retrieval/dedup.py) before scoring.

Providers MUST:
  * be import-safe with zero config (no network at import time),
  * degrade gracefully (return [] and log on error; never raise to caller),
  * respect `requires_key` / `enabled()` so the registry can skip them,
  * normalize results into `SourceCandidate` with a best-effort `canonical_id`.
"""

from __future__ import annotations

import abc
import dataclasses
import re
import time
from datetime import date
from typing import Literal, Optional

SourceKind = Literal["web", "academic", "preprint", "dataset", "code"]
ProviderKind = Literal["web", "academic"]


def json_safe(obj, _depth: int = 0):
    """Recursively coerce a value into JSON/msgpack-serializable types.

    Provider payloads (e.g. feedparser arXiv entries) can carry non-serializable
    objects like ``time.struct_time`` or ``datetime``; left in a candidate's
    ``raw`` they crash the LangGraph checkpointer (msgpack) once the candidate
    enters the graph state. Coerce: struct_time/datetime -> ISO string,
    bytes -> str, set/tuple -> list, unknown objects -> str. Bounded depth.
    """
    if _depth > 6:
        return None
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, time.struct_time):
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%S", obj)
        except Exception:
            return None
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj).decode("utf-8", "replace")
    iso = getattr(obj, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            try:
                out[str(k)] = json_safe(v, _depth + 1)
            except Exception:
                continue
        return out
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v, _depth + 1) for v in obj]
    try:
        return str(obj)
    except Exception:
        return None


@dataclasses.dataclass(slots=True)
class SourceCandidate:
    """A single normalized search hit, shared by every provider + the graph."""

    title: str
    url: str
    provider: str
    kind: SourceKind = "web"
    canonical_id: str = ""          # doi:.. | arxiv:.. | url:.. (filled by normalize())
    authors: list[str] = dataclasses.field(default_factory=list)
    venue: Optional[str] = None
    published_date: Optional[str] = None   # ISO-8601 (YYYY or YYYY-MM-DD)
    abstract: Optional[str] = None
    full_text: Optional[str] = None
    pdf_url: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    cited_by_count: Optional[int] = None
    is_oa: bool = False
    venue_quartile: Optional[str] = None   # Q1..Q4 if known (authority signal)
    raw: dict = dataclasses.field(default_factory=dict)
    # transient retrieval signals (not persisted directly)
    retrieval_score: float = 0.0           # provider/RRF relevance hint [0,1]
    subtopic_id: Optional[int] = None

    def normalize(self) -> "SourceCandidate":
        """Compute a stable canonical id AND make `raw` JSON/msgpack-safe.

        The raw sanitize is what prevents non-serializable provider payloads
        (e.g. feedparser's time.struct_time dates) from crashing the LangGraph
        checkpointer once this candidate enters the graph state.
        """
        self.canonical_id = canonical_id(doi=self.doi, arxiv_id=self.arxiv_id, url=self.url)
        if self.raw:
            self.raw = json_safe(self.raw)
        return self


# --------------------------------------------------------------------------- #
# Canonicalization helpers (also used by retrieval/dedup.py)
# --------------------------------------------------------------------------- #

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)
_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref|ref_src|mc_|igshid)", re.I)


def extract_doi(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _DOI_RE.search(text)
    return m.group(0).rstrip(").,;").lower() if m else None


def extract_arxiv_id(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _ARXIV_RE.search(text)
    return m.group(1) if m else None


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Lower host, strip tracking params + fragments + trailing slash."""
    if not url:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

        s = urlsplit(url.strip())
        host = (s.hostname or "").lower().removeprefix("www.")
        netloc = host + (f":{s.port}" if s.port else "")
        query = urlencode([(k, v) for k, v in parse_qsl(s.query) if not _TRACKING.match(k)])
        path = s.path.rstrip("/") or "/"
        return urlunsplit((s.scheme or "https", netloc, path, query, ""))
    except Exception:
        return url


def canonical_id(*, doi: Optional[str] = None, arxiv_id: Optional[str] = None,
                 url: Optional[str] = None) -> str:
    if doi:
        return f"doi:{doi.lower()}"
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    nu = normalize_url(url)
    if nu:
        return f"url:{nu}"
    return "url:unknown"


# --------------------------------------------------------------------------- #
# Provider ABC
# --------------------------------------------------------------------------- #

class SourceProvider(abc.ABC):
    name: str = "base"
    kind: ProviderKind = "web"
    requires_key: bool = False

    def enabled(self) -> bool:
        """Whether this provider is usable in the current environment."""
        return True

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        since: Optional[date] = None,
        language: Optional[str] = None,
    ) -> list[SourceCandidate]:
        """Return up to `limit` normalized candidates. Never raise."""
        raise NotImplementedError
