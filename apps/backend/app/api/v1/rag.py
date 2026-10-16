"""Rag endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1._phase import not_yet

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query")
def post_rag_0() -> dict:
    """Grounded answer with sources."""
    raise not_yet(7, "Grounded answer with sources")
