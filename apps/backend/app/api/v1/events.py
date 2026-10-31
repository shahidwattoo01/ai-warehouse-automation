"""Platform events for other systems (backlog PR-15): catalogue, replay and a live stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.auth import need
from app.services.events import events_service
from integration.events.publisher import PREFIX, catalog
from integration.vda5050.transport import MqttTransport

router = APIRouter(prefix="/events", tags=["events"])


def _pub():
    if events_service.publisher is None:
        raise HTTPException(409, detail={"code": "off", "message": "events are not running"})
    return events_service.publisher


@router.get("/catalog", dependencies=[need("dashboard:view")])
async def event_catalog() -> dict:
    """Topics and CloudEvents types, and where to subscribe."""
    pub = _pub()
    mqtt = isinstance(events_service.bus, MqttTransport)
    return {
        "events": catalog(),
        "transport": "mqtt" if mqtt else "memory",
        "mqtt_topic_filter": f"{PREFIX}/#",
        "stream": "/api/v1/events/stream?prefix=orders",
        "counts": pub.counts,
        "sequence": pub.seq,
        "subscribers": len(pub.subscribers),
    }


@router.get("", dependencies=[need("dashboard:view")])
async def replay(
    after: int = Query(0, ge=0),
    prefix: str | None = Query(None, max_length=40, description="e.g. orders, robots/fault"),
    limit: int = Query(200, le=2000),
) -> list[dict]:
    """Events after a sequence number (the last 2,000 are kept): catch up after a disconnect."""
    return _pub().replay(after, prefix, limit)


@router.get("/stream", dependencies=[need("dashboard:view")])
async def stream(prefix: str | None = Query(None, max_length=40)) -> StreamingResponse:
    """Server-Sent Events: every new event as it happens (`id:` is the sequence number, so a
    client resumes with /events?after=...). A comment is sent every 15 s to keep proxies open."""
    pub = _pub()
    queue = pub.subscribe()
    wanted = f"{PREFIX}/{prefix}" if prefix else None

    async def gen():
        try:
            yield f"retry: 3000\n: subscribed to {wanted or PREFIX + '/#'}\n\n"
            while True:
                try:
                    topic, event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if wanted and not topic.startswith(wanted):
                    continue
                payload = json.dumps({"topic": topic, **event})
                yield f"id: {event['sequence']}\nevent: {event['type']}\ndata: {payload}\n\n"
        finally:
            pub.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
