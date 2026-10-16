"""Helper for endpoints scheduled in a later phase."""

from fastapi import HTTPException, status


def not_yet(phase: int, what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={"code": "not_implemented", "message": f"{what} arrives in Phase {phase}"},
    )
