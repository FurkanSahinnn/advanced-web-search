"""
Finalizer node — marks the run and project done and emits the closing frame.
"""

from __future__ import annotations

import asyncio

from ...db import repositories
from ..events import emit


async def finalizer(state: dict) -> dict:
    run_id = state["run_id"]
    project_id = state["project_id"]

    try:
        await asyncio.to_thread(repositories.set_run_status, run_id, "done")
    except Exception:
        pass
    try:
        await asyncio.to_thread(repositories.set_project_status, project_id, "done")
    except Exception:
        pass

    emit("run_finished", run_id, node="finalizer", message="Run complete", status="done")
    return {}
