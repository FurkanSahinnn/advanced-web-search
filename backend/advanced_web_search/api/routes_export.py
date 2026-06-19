"""Citation & report export endpoints.

GET /runs/{run_id}/export       -> bibtex | ris | csl | markdown | html (file download)
GET /sources/{source_id}/cite   -> bibtex | ris (text/plain) for a single source
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from .. import export as export_mod
from ..db import repositories

router = APIRouter(tags=["export"])


# format -> (renderer, media_type, file extension)
_FORMATS = {
    "bibtex": (export_mod.to_bibtex, "application/x-bibtex; charset=utf-8", "bib"),
    "ris": (export_mod.to_ris, "application/x-research-info-systems; charset=utf-8", "ris"),
    "csl": (export_mod.to_csl_json, "application/json; charset=utf-8", "json"),
    "markdown": (None, "text/markdown; charset=utf-8", "md"),
    "html": (None, "text/html; charset=utf-8", "html"),
}


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: int,
    format: str = "markdown",
    kept_only: bool = True,
    print: bool = False,
    lang: Optional[str] = None,
) -> Response:
    fmt = (format or "").lower().strip()
    if fmt not in _FORMATS:
        raise HTTPException(status_code=415, detail=f"unknown export format: {format!r}")

    # Document formats (markdown/html) are language-aware: ``lang`` selects which
    # language's report to export. Reference formats (bibtex/ris/csl) describe the
    # sources only and are language-independent, so they ignore ``lang``.
    doc_lang = lang if fmt in ("markdown", "html") else None

    sources = await asyncio.to_thread(repositories.get_sources, run_id, kept_only)
    report = await asyncio.to_thread(repositories.get_report, run_id, doc_lang)

    project: Optional[dict] = None
    run = await asyncio.to_thread(repositories.get_run, run_id)
    if run and run.get("project_id") is not None:
        project = await asyncio.to_thread(repositories.get_project, int(run["project_id"]))
    project = project or {}

    # When format=html&print=true we serve the document INLINE (no attachment
    # disposition) with an auto-print script so the browser renders it and opens
    # the print dialog → the user saves as PDF. Everything else downloads.
    inline_print = fmt == "html" and bool(print)

    renderer, media_type, ext = _FORMATS[fmt]
    if fmt == "markdown":
        body = export_mod.report_to_markdown(report, sources, project)
    elif fmt == "html":
        body = export_mod.to_html(report, sources, project, auto_print=inline_print)
    else:
        body = renderer(sources)

    if inline_print:
        return Response(content=body, media_type="text/html; charset=utf-8")

    if doc_lang:
        filename = f"advanced-web-search-{run_id}-{doc_lang}.{ext}"
    else:
        filename = f"advanced-web-search-{run_id}.{ext}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sources/{source_id}/cite")
async def cite_source(source_id: int, format: str = "bibtex") -> Response:
    fmt = (format or "").lower().strip()
    if fmt not in ("bibtex", "ris"):
        raise HTTPException(status_code=415, detail=f"unknown citation format: {format!r}")

    src = await asyncio.to_thread(repositories.get_source, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="source not found")

    body = export_mod.single_citation(src, fmt)
    return Response(content=body, media_type="text/plain; charset=utf-8")
