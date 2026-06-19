"""
Citation & report export.

Pure string templating — no third-party dependencies. Every function is
defensive: missing/None fields collapse to sensible blanks and never raise.

A "source" here is a DB row dict as returned by `repositories.get_sources` /
`get_source` (authors is a JSON-encoded string; published_date is 'YYYY' or
'YYYY-MM-DD'). DOI is best-effort extracted from canonical_id / url.

Public surface:
  to_bibtex, to_ris, to_csl_json, report_to_markdown, to_html, single_citation
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# Field extraction helpers
# --------------------------------------------------------------------------- #

def _s(value: Any) -> str:
    """Coerce any value to a stripped string (None -> '')."""
    if value is None:
        return ""
    return str(value).strip()


def _authors(src: dict) -> list[str]:
    """Parse the `authors` field into a list of name strings.

    Handles a JSON-encoded string, an already-decoded list, or None. Each entry
    may be a plain string or a dict (we look at common name keys).
    """
    raw = (src or {}).get("authors")
    parsed: Any = raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            # Treat a non-JSON string as a single author name.
            return [raw]
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, (list, tuple)):
        return [_s(parsed)] if _s(parsed) else []

    out: list[str] = []
    for a in parsed:
        if a is None:
            continue
        if isinstance(a, str):
            name = a.strip()
        elif isinstance(a, dict):
            name = (
                _s(a.get("name"))
                or _s(a.get("display_name"))
                or " ".join(p for p in (_s(a.get("given")), _s(a.get("family"))) if p)
                or _s(a.get("raw"))
            )
        else:
            name = _s(a)
        if name:
            out.append(name)
    return out


def _year(src: dict) -> str:
    """First 4 chars of published_date if they look like a year, else ''."""
    d = _s((src or {}).get("published_date"))
    if len(d) >= 4 and d[:4].isdigit():
        return d[:4]
    return ""


def _doi(src: dict) -> str:
    """Best-effort DOI extraction from doi/canonical_id/url fields (no leading 'doi:')."""
    src = src or {}
    candidates = [
        _s(src.get("doi")),
        _s(src.get("canonical_id")),
        _s(src.get("url")),
        _s(src.get("pdf_url")),
    ]
    for c in candidates:
        if not c:
            continue
        m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", c, re.IGNORECASE)
        if m:
            return m.group(0).rstrip(".,;)")
    return ""


def _name_parts(name: str) -> tuple[str, str]:
    """Split a display name into (family, given). Best-effort, never raises."""
    name = _s(name)
    if not name:
        return ("", "")
    if "," in name:
        family, _, given = name.partition(",")
        return (family.strip(), given.strip())
    bits = name.split()
    if len(bits) == 1:
        return (bits[0], "")
    return (bits[-1], " ".join(bits[:-1]))


def _last_name(name: str) -> str:
    return _name_parts(name)[0]


def _cite_key(src: dict, i: int) -> str:
    """A reasonably unique, human-friendly BibTeX/RIS key.

    Shape: <FirstAuthorLastname><Year><providerish>. Falls back to
    'aws<id>' or 'aws<i>' when nothing usable exists.
    """
    src = src or {}
    authors = _authors(src)
    last = _last_name(authors[0]) if authors else ""
    last = re.sub(r"[^A-Za-z0-9]", "", last)
    year = _year(src)
    prov = re.sub(r"[^A-Za-z0-9]", "", _s(src.get("provider")))[:8]
    parts = [p for p in (last, year, prov) if p]
    key = "".join(parts)
    if not key:
        sid = _s(src.get("id"))
        key = f"aws{sid}" if sid else f"aws{i}"
    # Disambiguate keys that would otherwise collide across the list.
    return key


def _is_article(src: dict) -> bool:
    """Heuristic: academic/preprint sources with a venue are @article/JOUR."""
    src = src or {}
    kind = _s(src.get("kind")).lower()
    if kind in ("academic", "preprint", "journal", "paper", "article"):
        return True
    if _s(src.get("venue")):
        return True
    return False


# --------------------------------------------------------------------------- #
# BibTeX
# --------------------------------------------------------------------------- #

def _bib_escape(text: str) -> str:
    """Escape characters that break BibTeX field values."""
    text = _s(text)
    if not text:
        return ""
    # Escape backslash first, then special chars.
    text = text.replace("\\", r"\textbackslash{}")
    for ch in "&%$#_{}":
        text = text.replace(ch, "\\" + ch)
    text = text.replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}")
    # Collapse newlines.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _bibtex_entry(src: dict, i: int, used_keys: set[str]) -> str:
    src = src or {}
    is_art = _is_article(src)
    etype = "article" if is_art else "misc"

    key = _cite_key(src, i)
    base = key
    n = 1
    while key in used_keys:
        n += 1
        key = f"{base}{chr(ord('a') + n - 2)}" if n - 2 < 26 else f"{base}{n}"
    used_keys.add(key)

    fields: list[tuple[str, str]] = []
    title = _bib_escape(src.get("title")) or _bib_escape(src.get("canonical_id"))
    if title:
        fields.append(("title", title))
    authors = _authors(src)
    if authors:
        fields.append(("author", " and ".join(_bib_escape(a) for a in authors)))
    year = _year(src)
    if year:
        fields.append(("year", year))
    venue = _bib_escape(src.get("venue"))
    if venue:
        fields.append(("journal" if is_art else "howpublished", venue))
    doi = _doi(src)
    if doi:
        fields.append(("doi", _bib_escape(doi)))
    url = _s(src.get("url")) or _s(src.get("pdf_url"))
    if url:
        fields.append(("url", _bib_escape(url)))
    note_bits = [b for b in (_s(src.get("provider")), _s(src.get("kind"))) if b]
    if note_bits:
        fields.append(("note", _bib_escape(" / ".join(note_bits))))

    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields)
    return f"@{etype}{{{key},\n{body}\n}}"


def to_bibtex(sources: list[dict]) -> str:
    """Render sources as a BibTeX bibliography string."""
    sources = sources or []
    used: set[str] = set()
    entries = [_bibtex_entry(s, i + 1, used) for i, s in enumerate(sources)]
    return "\n\n".join(entries) + ("\n" if entries else "")


# --------------------------------------------------------------------------- #
# RIS
# --------------------------------------------------------------------------- #

def _ris_clean(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", _s(text)).strip()


def _ris_record(src: dict) -> str:
    src = src or {}
    is_art = _is_article(src)
    lines: list[str] = []
    lines.append(f"TY  - {'JOUR' if is_art else 'ELEC'}")

    title = _ris_clean(src.get("title")) or _ris_clean(src.get("canonical_id"))
    if title:
        lines.append(f"TI  - {title}")
    for a in _authors(src):
        family, given = _name_parts(a)
        au = f"{family}, {given}".strip().rstrip(",") if family else _ris_clean(a)
        if au:
            lines.append(f"AU  - {au}")
    year = _year(src)
    if year:
        lines.append(f"PY  - {year}")
    venue = _ris_clean(src.get("venue"))
    if venue:
        lines.append(f"{'JO' if is_art else 'T2'}  - {venue}")
    doi = _doi(src)
    if doi:
        lines.append(f"DO  - {doi}")
    url = _s(src.get("url")) or _s(src.get("pdf_url"))
    if url:
        lines.append(f"UR  - {_ris_clean(url)}")
    abstract = _ris_clean(src.get("abstract"))
    if abstract:
        lines.append(f"AB  - {abstract}")
    lines.append("ER  - ")
    return "\n".join(lines)


def to_ris(sources: list[dict]) -> str:
    """Render sources as RIS records."""
    sources = sources or []
    records = [_ris_record(s) for s in sources]
    return "\n\n".join(records) + ("\n" if records else "")


# --------------------------------------------------------------------------- #
# CSL-JSON
# --------------------------------------------------------------------------- #

def _csl_item(src: dict, i: int) -> dict:
    src = src or {}
    item: dict[str, Any] = {
        "id": _cite_key(src, i),
        "type": "article-journal" if _is_article(src) else "webpage",
    }
    title = _s(src.get("title")) or _s(src.get("canonical_id"))
    if title:
        item["title"] = title

    authors = []
    for a in _authors(src):
        family, given = _name_parts(a)
        if family or given:
            entry: dict[str, str] = {}
            if family:
                entry["family"] = family
            if given:
                entry["given"] = given
            authors.append(entry)
    if authors:
        item["author"] = authors

    year = _year(src)
    if year:
        try:
            item["issued"] = {"date-parts": [[int(year)]]}
        except Exception:
            pass

    venue = _s(src.get("venue"))
    if venue:
        item["container-title"] = venue
    doi = _doi(src)
    if doi:
        item["DOI"] = doi
    url = _s(src.get("url")) or _s(src.get("pdf_url"))
    if url:
        item["URL"] = url
    abstract = _s(src.get("abstract"))
    if abstract:
        item["abstract"] = abstract
    return item


def to_csl_json(sources: list[dict]) -> str:
    """Render sources as a CSL-JSON array string."""
    sources = sources or []
    items = [_csl_item(s, i + 1) for i, s in enumerate(sources)]
    return json.dumps(items, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Human-readable reference line
# --------------------------------------------------------------------------- #

def _reference_line(src: dict) -> str:
    """A compact human-readable citation: Authors (Year). Title. Venue. DOI/URL."""
    src = src or {}
    parts: list[str] = []
    authors = _authors(src)
    if authors:
        if len(authors) > 6:
            authors = authors[:6] + ["et al."]
        parts.append(", ".join(authors))
    year = _year(src)
    if year:
        parts.append(f"({year})")
    title = _s(src.get("title")) or _s(src.get("canonical_id"))
    if title:
        parts.append(title.rstrip(".") + ".")
    venue = _s(src.get("venue"))
    if venue:
        parts.append(venue.rstrip(".") + ".")
    doi = _doi(src)
    if doi:
        parts.append(f"https://doi.org/{doi}")
    else:
        url = _s(src.get("url")) or _s(src.get("pdf_url"))
        if url:
            parts.append(url)
    line = " ".join(p for p in parts if p).strip()
    return line or _s(src.get("canonical_id")) or "(untitled source)"


# --------------------------------------------------------------------------- #
# Reference numbering ([n] <-> source)
# --------------------------------------------------------------------------- #

def report_references(report: Optional[dict]) -> list[int]:
    """Parse a report row's persisted [n]->source-id mapping (the `ref_ids` JSON
    column) into a list of source ids in citation order (index 0 == marker [1]).

    Returns [] for older reports that predate the mapping, signalling callers to
    fall back to their prior (score-ordered) behaviour.
    """
    raw = (report or {}).get("ref_ids")
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _numbered_refs(report: Optional[dict], sources: list[dict]) -> list[tuple[int, dict]]:
    """Pair each source with its true citation number n, in [n] order.

    When the report carries a [n]->source mapping, every entry keeps its real n
    (so the printed list lines up with the inline [n] markers in the body, even
    if a numbered source is absent from `sources` — that number is simply
    skipped rather than shifting the rest). Without a mapping (older reports) we
    fall back to numbering the given sources 1..k in their incoming order.
    """
    refs = report_references(report)
    if not refs:
        return list(enumerate(sources or [], 1))
    by_id: dict[Any, dict] = {}
    for s in sources or []:
        sid = s.get("id")
        if sid is not None and sid not in by_id:
            by_id[sid] = s
    out: list[tuple[int, dict]] = []
    for n, sid in enumerate(refs, 1):
        s = by_id.get(sid)
        if s is not None:
            out.append((n, s))
    return out


# --------------------------------------------------------------------------- #
# Markdown report
# --------------------------------------------------------------------------- #

def report_to_markdown(report: Optional[dict], sources: list[dict], project: dict) -> str:
    """Project title + root query, the report markdown, then a references list.

    The references are numbered to match the inline [n] markers in the body when
    the report carries a [n]->source mapping (see ``_numbered_refs``).
    """
    project = project or {}
    sources = sources or []
    title = _s(project.get("title")) or _s(project.get("root_query")) or "Advanced Web Search Report"
    root_query = _s(project.get("root_query"))

    out: list[str] = [f"# {title}", ""]
    if root_query and root_query != title:
        out.append(f"> {root_query}")
        out.append("")

    body = _s((report or {}).get("markdown")) if report else ""
    if body:
        out.append(body)
        out.append("")

    out.append("## Kaynaklar / References")
    out.append("")
    numbered = _numbered_refs(report, sources)
    if numbered:
        for n, s in numbered:
            out.append(f"{n}. {_reference_line(s)}")
    else:
        out.append("_—_")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# HTML (print-friendly, self-contained)
# --------------------------------------------------------------------------- #

_INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _md_inline(text: str) -> str:
    """Escape HTML, then apply a tiny subset of inline markdown."""
    esc = _html.escape(_s(text), quote=False)
    esc = _INLINE_LINK.sub(
        lambda m: f'<a href="{_html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        esc,
    )
    esc = _BOLD.sub(r"<strong>\1</strong>", esc)
    esc = _ITALIC.sub(r"<em>\1</em>", esc)
    return esc


def _md_to_html(md: str) -> str:
    """Minimal markdown -> HTML: headings, lists, paragraphs, links, hr.

    Not a full converter — just enough for a clean printable document.
    """
    md = _s(md)
    if not md:
        return ""
    html_lines: list[str] = []
    list_open: Optional[str] = None  # 'ul' | 'ol'
    para: list[str] = []

    def flush_para() -> None:
        if para:
            html_lines.append(f"<p>{_md_inline(' '.join(para))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            html_lines.append(f"</{list_open}>")
            list_open = None

    for raw_line in md.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_para()
            close_list()
            continue

        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h:
            flush_para()
            close_list()
            level = len(h.group(1))
            html_lines.append(f"<h{level}>{_md_inline(h.group(2))}</h{level}>")
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            close_list()
            html_lines.append("<hr/>")
            continue

        ol = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        ul = re.match(r"^[-*+]\s+(.*)$", stripped)
        if ol or ul:
            flush_para()
            want = "ol" if ol else "ul"
            if list_open != want:
                close_list()
                html_lines.append(f"<{want}>")
                list_open = want
            content = (ol or ul).group(1)
            html_lines.append(f"<li>{_md_inline(content)}</li>")
            continue

        # plain paragraph text (accumulate)
        close_list()
        para.append(stripped)

    flush_para()
    close_list()
    return "\n".join(html_lines)


_HTML_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  font-family: Georgia, 'Times New Roman', serif;
  color: #1a1a1a;
  background: #fff;
  line-height: 1.6;
  max-width: 46rem;
  margin: 2.5rem auto;
  padding: 0 1.5rem;
}
h1 { font-size: 1.9rem; line-height: 1.25; margin: 0 0 .25rem; }
h2 { font-size: 1.4rem; margin: 2rem 0 .6rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
h3 { font-size: 1.15rem; margin: 1.5rem 0 .4rem; }
p { margin: .8rem 0; }
a { color: #14507a; }
ul, ol { margin: .8rem 0 .8rem 1.4rem; padding: 0; }
li { margin: .25rem 0; }
hr { border: 0; border-top: 1px solid #ddd; margin: 2rem 0; }
blockquote { margin: 1rem 0; padding: .25rem 0 .25rem 1rem; border-left: 3px solid #ccc; color: #555; font-style: italic; }
.aws-subtitle { color: #555; font-style: italic; margin: 0 0 1.5rem; }
.aws-refs { margin-top: 2.5rem; }
.aws-refs ol { font-size: .95rem; }
.aws-refs li { margin: .5rem 0; word-break: break-word; }
.aws-footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #eee; color: #888; font-size: .8rem; }
@media print {
  body { margin: 0; max-width: none; font-size: 11pt; }
  a { color: #000; text-decoration: none; }
  h2 { page-break-after: avoid; }
  li, p { page-break-inside: avoid; }
  .aws-footer { display: none; }
}
""".strip()


def to_html(
    report: Optional[dict],
    sources: list[dict],
    project: dict,
    auto_print: bool = False,
) -> str:
    """A self-contained, print-friendly HTML document (Ctrl+P -> PDF).

    When ``auto_print`` is True a tiny script is injected before ``</body>`` so
    the page opens the browser's print dialog automatically once loaded — the
    user then picks "Save as PDF". The page is otherwise unchanged.
    """
    project = project or {}
    sources = sources or []
    title = _s(project.get("title")) or _s(project.get("root_query")) or "Advanced Web Search Report"
    root_query = _s(project.get("root_query"))

    body_md = _s((report or {}).get("markdown")) if report else ""
    body_html = _md_to_html(body_md) if body_md else "<p><em>No report available.</em></p>"

    subtitle = ""
    if root_query and root_query != title:
        subtitle = f'<p class="aws-subtitle">{_html.escape(root_query)}</p>'

    numbered = _numbered_refs(report, sources)
    if numbered:
        # `value="n"` pins each entry to its true citation number so the printed
        # list lines up with the inline [n] markers (and survives any skips).
        refs = "\n".join(
            f'<li value="{n}">{_md_inline(_reference_line(s))}</li>' for n, s in numbered
        )
        refs_html = f"<ol>{refs}</ol>"
    else:
        refs_html = "<p><em>—</em></p>"

    consensus = _s((report or {}).get("consensus_summary")) if report else ""
    consensus_html = (
        f'<blockquote>{_md_inline(consensus)}</blockquote>' if consensus else ""
    )

    auto_print_script = (
        "<script>window.addEventListener('load',function(){"
        "setTimeout(function(){window.print();},350);});</script>"
        if auto_print
        else ""
    )

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_html.escape(title)}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
<h1>{_html.escape(title)}</h1>
{subtitle}
{consensus_html}
<article>
{body_html}
</article>
<section class="aws-refs">
<h2>Kaynaklar / References</h2>
{refs_html}
</section>
<footer class="aws-footer">Advanced Web Search &middot; {len(sources)} source(s)</footer>
{auto_print_script}
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Single-source citation
# --------------------------------------------------------------------------- #

def single_citation(src: dict, fmt: str) -> str:
    """Render one source as a `bibtex` or `ris` citation string."""
    src = src or {}
    fmt = (fmt or "").lower().strip()
    if fmt == "ris":
        return to_ris([src])
    # default to bibtex for anything else
    return to_bibtex([src])
