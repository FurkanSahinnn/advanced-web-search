"""Per-run source list + report endpoints."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter

from ..db import repositories
from ..models.schemas import ReportOut, SourceOut
from .routes_projects import report_out, source_out

router = APIRouter(tags=["sources"])


@router.get("/runs/{run_id}/sources", response_model=list[SourceOut])
async def list_run_sources(run_id: int, kept_only: bool = False) -> list[SourceOut]:
    rows = await asyncio.to_thread(repositories.get_sources, run_id, kept_only)
    return [source_out(r) for r in rows]


@router.get("/runs/{run_id}/report", response_model=Optional[ReportOut])
async def get_run_report(run_id: int, lang: Optional[str] = None) -> Optional[ReportOut]:
    row = await asyncio.to_thread(repositories.get_report, run_id, lang)
    if not row:
        return None
    return report_out(row)


@router.get("/runs/{run_id}/reports", response_model=list[ReportOut])
async def list_run_reports(run_id: int) -> list[ReportOut]:
    rows = await asyncio.to_thread(repositories.get_reports, run_id)
    return [report_out(r) for r in rows]
