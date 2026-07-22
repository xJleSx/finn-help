from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.db.models import User
from src.interfaces.api.auth import require_user

logger = logging.getLogger(__name__)

sse_router = APIRouter()

MAX_SUBSCRIBERS = 100
_signal_subscribers: list[asyncio.Queue] = []


async def _event_generator(request: Request, queue: asyncio.Queue) -> Any:
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\nretry: 3000\n\n"
    finally:
        if queue in _signal_subscribers:
            _signal_subscribers.remove(queue)


@sse_router.get("/api/signals/stream")
async def signal_stream(
    request: Request,
    user: User = Depends(require_user),
):
    if len(_signal_subscribers) >= MAX_SUBSCRIBERS:
        logger.warning("Max SSE subscribers reached (%d)", MAX_SUBSCRIBERS)
        from fastapi.responses import JSONResponse
        from fastapi import status
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Too many subscribers. Try again later."},
        )
    queue: asyncio.Queue = asyncio.Queue()
    _signal_subscribers.append(queue)
    return StreamingResponse(
        _event_generator(request, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def broadcast_signal_event(event: dict[str, Any]) -> None:
    event["_timestamp"] = datetime.now(timezone.utc).isoformat()
    for queue in _signal_subscribers[:]:
        try:
            await queue.put(event)
        except Exception:
            _signal_subscribers.remove(queue)
