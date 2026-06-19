"""Run control + the live SSE agent-trace stream."""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..config import language_name
from ..db import repositories
from ..graph import runner
from ..llm.provider import chat
from ..models.schemas import ApprovalDecision, AskAnswerOut, AskRequest, RunOut
from ..retrieval import vector_store
from ..utils.text import detect_language, truncate
from .routes_projects import _run_out

# Ask-the-Report retrieval/answer budget.
_ASK_TOP_K = 8
_ASK_CHUNK_CHARS = 700
_ASK_MAX_TOKENS = 800
_CITE_RE = re.compile(r"\[(\d+)\]")

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


@router.post("/runs/{run_id}/ask", response_model=AskAnswerOut)
async def ask_run(run_id: int, body: AskRequest) -> AskAnswerOut:
    """Answer a follow-up question grounded ONLY in this run's gathered sources.

    Retrieves the most relevant chunks from the run's own hybrid index, numbers
    their sources [1..k], and asks the LLM to answer using only those excerpts and
    cite [n]. No new web calls; if nothing relevant is indexed the answer is
    flagged ungrounded rather than guessed. The Q&A is persisted so a reopened run
    keeps its history.
    """
    run = await asyncio.to_thread(repositories.get_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="empty question")

    lang_code = (body.language or "").strip()
    if not lang_code:
        try:
            lang_code = detect_language(question)
        except Exception:
            lang_code = "en"
    lang = language_name(lang_code)

    # --- retrieve from THIS run's own indexed chunks ---
    try:
        hits = await vector_store.hybrid_search(question, run_id, top_k=_ASK_TOP_K)
    except Exception:
        hits = []

    order_sids: list[int] = []
    chunks_by_sid: dict[int, list[str]] = {}
    for h in hits or []:
        sid = h.get("source_id")
        if not isinstance(sid, int):
            continue
        if sid not in chunks_by_sid:
            chunks_by_sid[sid] = []
            order_sids.append(sid)
        text = h.get("text") or ""
        if text:
            chunks_by_sid[sid].append(text)

    if not order_sids:
        # Nothing relevant in this run's sources — be honest, don't hallucinate.
        ask_id = await asyncio.to_thread(
            repositories.add_run_ask, run_id, question, "", [], False
        )
        return AskAnswerOut(id=ask_id, question=question, answer="",
                            references=[], grounded=False)

    # Source titles for the numbered excerpt block. Defensive like the rest of
    # this handler: a DB read hiccup degrades to blank titles, never a 500.
    try:
        src_rows = await asyncio.gather(
            *[asyncio.to_thread(repositories.get_source, sid) for sid in order_sids]
        )
    except Exception:
        src_rows = [None] * len(order_sids)
    titles = {sid: ((row or {}).get("title") or "")
              for sid, row in zip(order_sids, src_rows)}

    n_of_source = {sid: i + 1 for i, sid in enumerate(order_sids)}
    blocks = [
        f"[{n_of_source[sid]}] {titles.get(sid, '')}\n"
        f"{truncate(' '.join(chunks_by_sid[sid]), _ASK_CHUNK_CHARS)}"
        for sid in order_sids
    ]
    context = "\n\n".join(blocks)

    system = (
        "You answer a follow-up question using ONLY the provided numbered source "
        "excerpts from a research run. Cite every factual sentence with an inline "
        "[n] marker matching the excerpts. If the excerpts do not contain the "
        "answer, say so plainly — NEVER use outside knowledge."
    )
    user = (
        f"QUESTION:\n{question}\n\nSOURCE EXCERPTS:\n{context}\n\n"
        f"Answer in {lang}. Cite the excerpts you use with their [n] markers. If "
        "the excerpts do not address the question, say that they do not."
    )
    try:
        answer = await chat(
            "synthesizer",
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=_ASK_MAX_TOKENS,
        )
    except Exception:
        answer = ""
    answer = (answer or "").strip()

    cited_ns = {int(x) for x in _CITE_RE.findall(answer)}
    grounded = bool(answer) and any(1 <= n <= len(order_sids) for n in cited_ns)
    # references[i] is the source for inline marker [i+1] (dense, self-contained
    # numbering for this answer). Empty for an ungrounded "not found" answer.
    references = order_sids if grounded else []

    ask_id = await asyncio.to_thread(
        repositories.add_run_ask, run_id, question, answer, references, grounded
    )
    return AskAnswerOut(id=ask_id, question=question, answer=answer,
                        references=references, grounded=grounded)
