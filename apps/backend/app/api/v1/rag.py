"""Rag endpoints (TRD Section 7): the knowledge assistant (Phase 7).

    POST /rag/query                  grounded answer with its sources, or "not covered"
    GET  /rag/status                 what is loaded (store, retriever, answer writer)
    GET  /rag/documents              the documents and their sections
    GET  /rag/sections/{section_id}  the full text of one section (source viewer)

Answering runs in a worker thread (app/services/knowledge.py): the simulator keeps ticking.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import need
from app.services.knowledge import knowledge

router = APIRouter(prefix="/rag", tags=["rag"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    doc_type: Literal["manual", "safety", "maintenance", "sop", "policy"] | None = None
    k: int | None = Field(default=None, ge=1, le=10, description="passages to retrieve")


def _unavailable(err: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "knowledge_unavailable", "message": str(err)},
    )


@router.post("/query", dependencies=[need("copilot:use")])
async def query(body: Question) -> dict:
    """Answer from the warehouse documents, citing the sections used."""
    try:
        return await knowledge.ask(body.question.strip(), body.doc_type, body.k)
    except RuntimeError as err:
        raise _unavailable(err) from err


@router.get("/status", dependencies=[need("copilot:use")])
async def rag_status() -> dict:
    """Which knowledge base is loaded (also starts loading it in the background)."""
    knowledge.warm_up()
    return knowledge.status()


@router.get("/documents", dependencies=[need("copilot:use")])
async def documents() -> list[dict]:
    if knowledge.kb is None:
        knowledge.warm_up()
        raise _unavailable(RuntimeError("the knowledge base is still loading; try again"))
    return knowledge.documents()


@router.get("/sections/{section_id}", dependencies=[need("copilot:use")])
async def section(section_id: str) -> dict:
    if knowledge.kb is None:
        knowledge.warm_up()
        raise _unavailable(RuntimeError("the knowledge base is still loading; try again"))
    found = knowledge.section(section_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No section {section_id}")
    return found
