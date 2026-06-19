"""Run control + the live SSE agent-trace stream."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..db import repositories
from ..graph import runner
from ..models.schemas import ApprovalDecision, RunOut
from .routes_projects import _run_out

try:  # orjson is a declared dependency; fall back to stdlib json if missing.
    import orjson

    def _dumps(obj) -> str:
        return orjson.dumps(obj).decode("utf-8")
except Exception:  # pragma: no cover
    import json

    def _dumps(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str)


router = APIRouter(tags=["research"])


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int) -> EventSourceResponse:
    async def gen():
        try:
            async for ev in runner.run_stream(run_id):
                yield {"data": _dumps(ev)}
        except asyncio.CancelledError:
            # Client disconnected — exit quietly.
            return

    return EventSourceResponse(gen(), ping=15000)


@router.post("/runs/{run_id}/approve")
async def approve_run(run_id: int, body: ApprovalDecision) -> dict:
    await runner.approve(run_id, body.model_dump())
    return {"ok": True}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int) -> dict:
    await runner.cancel(run_id)
    return {"ok": True}


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int) -> RunOut:
    row = await asyncio.to_thread(repositories.get_run, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_out(row)
