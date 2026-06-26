"""
Shared async HTTP client with a polite User-Agent, retries, on-disk caching
for GET requests, and global concurrency limiting. Every source provider and
the verifier use this so we are a good API citizen (polite pool, backoff) and
avoid re-fetching the same URL repeatedly within a run.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import time
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from ..config import get_settings

_USER_AGENT = "AdvancedWebSearch/0.1 (+https://github.com/; research workbench)"
_client: httpx.AsyncClient | None = None
_sem = asyncio.Semaphore(12)

# Hostnames that must never be fetched (SSRF guard). The Verifier and full-text
# fetch follow arbitrary source URLs, so any URL that resolves to localhost or a
# private/link-local range is rejected before a request is ever made.
_BLOCKED_HOSTNAMES = {"localhost", "ip6-localhost", "ip6-loopback"}


def is_safe_url(url: str) -> bool:
    """Return True only for public http(s) URLs (SSRF guard).

    Rejects: non-http(s) schemes; literal IPs that are loopback / private /
    link-local / reserved / unspecified (e.g. 127.x, 10.x, 192.168.x,
    172.16-31.x, 169.254.x, 0.0.0.0, ::1); and obvious internal hostnames
    ('localhost', anything ending in '.local'/'.internal', bare hostnames with
    no dot). Best-effort and conservative: anything we cannot confidently
    classify as public is treated as unsafe.
    """
    try:
        parts = urlsplit((url or "").strip())
    except Exception:
        return False

    if parts.scheme.lower() not in ("http", "https"):
        return False

    host = (parts.hostname or "").strip().lower()
    if not host:
        return False

    if host in _BLOCKED_HOSTNAMES:
        return False
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".localhost"):
        return False

    # Literal IP? Block any non-global address.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
        return True

    # Hostname (not a literal IP). Block bare single-label names (no dot), which
    # are intranet-style names that can resolve to internal hosts.
    if "." not in host:
        return False

    return True


def _contact() -> str:
    return get_settings().contact_email or "advanced-web-search@localhost"


def user_agent() -> str:
    return f"{_USER_AGENT} mailto:{_contact()}"


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={"User-Agent": user_agent()},
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _cache_file(key: str):
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return get_settings().http_cache_path / f"{h}.json"


async def fetch_json(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    cache_ttl: int = 86_400,
    retries: int = 3,
) -> Optional[Any]:
    """GET a JSON endpoint with disk caching + exponential backoff. Returns None on failure."""
    cache_key = url + "?" + json.dumps(params or {}, sort_keys=True)
    cf = _cache_file(cache_key)
    if cache_ttl > 0 and cf.exists() and (time.time() - cf.stat().st_mtime) < cache_ttl:
        try:
            return json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            pass

    client = await get_client()
    delay = 1.0
    for attempt in range(retries):
        try:
            async with _sem:
                resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            resp.raise_for_status()
            data = resp.json()
            try:
                cf.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass
            return data
        except Exception:
            if attempt == retries - 1:
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None


async def fetch_text(
    url: str,
    *,
    headers: Optional[dict] = None,
    retries: int = 2,
    timeout: float = 25.0,
) -> Optional[str]:
    """GET raw text/HTML. Returns None on failure (used by the verifier + full-text extraction)."""
    if not is_safe_url(url):
        return None
    client = await get_client()
    delay = 1.0
    for attempt in range(retries):
        try:
            async with _sem:
                resp = await client.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception:
            if attempt == retries - 1:
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None


async def fetch_bytes(
    url: str,
    *,
    headers: Optional[dict] = None,
    retries: int = 2,
    max_bytes: int = 8_000_000,
    total_timeout: float = 60.0,
) -> Optional[bytes]:
    """GET raw binary content (e.g. a PDF), capped at ``max_bytes``.

    Streams the response so we stop reading once the cap is exceeded, mirroring
    the shared client/semaphore usage of the other fetchers. Returns None on
    any failure (network, status, oversize). Never raises.

    ``total_timeout`` is a WALL-CLOCK cap on the streaming read: httpx's 25s is a
    per-read (per-chunk) timeout, so a slow-drip server emitting a trickle just
    inside each window can hold the connection open far longer. We abort once the
    total elapsed download time exceeds ``total_timeout`` (slowloris guard).
    """
    if not is_safe_url(url):
        return None
    client = await get_client()
    delay = 1.0
    for attempt in range(retries):
        try:
            async with _sem:
                async with client.stream("GET", url, headers=headers) as resp:
                    resp.raise_for_status()
                    buf = bytearray()
                    start = time.monotonic()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            return None
                        if time.monotonic() - start > total_timeout:
                            return None
                    return bytes(buf)
        except Exception:
            if attempt == retries - 1:
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None


async def check_url_alive(url: str) -> tuple[bool, int]:
    """HEAD (falling back to GET) a URL; return (alive, status_code). Used by the Verifier."""
    if not is_safe_url(url):
        return (False, 0)
    client = await get_client()
    try:
        async with _sem:
            resp = await client.head(url, timeout=12.0)
        if resp.status_code >= 400 or resp.status_code == 405:
            async with _sem:
                resp = await client.get(url, timeout=15.0)
        return (resp.status_code < 400, resp.status_code)
    except Exception:
        return (False, 0)
