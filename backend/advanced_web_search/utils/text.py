"""Text utilities: cleaning, chunking, and full-text extraction from HTML."""

from __future__ import annotations

import re
from typing import Optional

_WS = re.compile(r"[ \t ]+")
_NL = re.compile(r"\n{3,}")


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


def truncate(text: Optional[str], limit: int = 2000) -> str:
    t = clean_text(text)
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Paragraph-aware sliding chunks for embedding."""
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= max_chars:
                buf = p
            else:
                # hard-split an over-long paragraph
                start = 0
                while start < len(p):
                    chunks.append(p[start:start + max_chars])
                    start += max_chars - overlap
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def extract_main_text(html: str, url: Optional[str] = None) -> str:
    """Best-effort article extraction. Tries trafilatura, falls back to selectolax."""
    if not html:
        return ""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html, url=url, include_comments=False, include_tables=False, favor_recall=True
        )
        if extracted and len(extracted) > 200:
            return clean_text(extracted)
    except Exception:
        pass
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for tag in tree.css("script, style, nav, header, footer, aside"):
            tag.decompose()
        body = tree.body
        return clean_text(body.text(separator="\n") if body else "")
    except Exception:
        return ""


def detect_language(text: Optional[str]) -> str:
    """Very cheap heuristic TR/EN detector (no heavy deps); returns 'tr'|'en'|'auto'."""
    if not text:
        return "auto"
    sample = text.lower()[:2000]
    tr_markers = sum(sample.count(c) for c in "çğıöşü")
    tr_words = sum(sample.count(w) for w in (" ve ", " bir ", " için ", " ile ", " bu "))
    if tr_markers > 4 or tr_words > 2:
        return "tr"
    return "en"
