"""SSE realtime stream (API_SPECIFICATION.md section 15).

Events are ephemeral: clients refetch canonical resources after reconnect.
Fan-out path: durable state changes write `sse.event` outbox rows; a tail
task in this module relays new rows to the in-process bus, which feeds every
connected stream. Own-process or not, this keeps delivery order and removes
double-publishing between app processes.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, tuple_

from app.core import config
from app.core.db import get_session_factory, utcnow
from app.core.errors import ApiError
from app.core.sse import bus, format_sse
from app.deps import require_workspace_access, resolve_session_user
from app.models.models import OutboxMessage, User

logger = logging.getLogger("flowsentry.stream")

router = APIRouter(prefix="/events", tags=["realtime"])

TAIL_POLL_SECONDS = 0.5
TAIL_LOOKBACK_SECONDS = 10.0
_SEEN_LIMIT = 1000


class _TailState:
    last_ts: Any = None
    last_id: Any = None
    seen: set[str] = set()
    task: asyncio.Task | None = None
    lock = threading.Lock()


tail_state = _TailState()
_tail_fail_count = 0


def _poll_tail_rows():
    factory = get_session_factory()
    db = factory()
    try:
        since = tail_state.last_ts or (utcnow() - timedelta(seconds=TAIL_LOOKBACK_SECONDS))
        query = select(OutboxMessage).where(
            OutboxMessage.aggregate_type == "sse_event",
            OutboxMessage.created_at >= since,
        )
        if tail_state.last_ts is not None and tail_state.last_id is not None:
            query = query.where(tuple_(OutboxMessage.created_at, OutboxMessage.id) >
                                tuple_(tail_state.last_ts, tail_state.last_id))
        rows = (
            db.execute(
                query.order_by(OutboxMessage.created_at, OutboxMessage.id)
                .limit(500)
            )
            .scalars()
            .all()
        )
        return rows
    finally:
        db.close()


async def _tail_loop() -> None:
    global _tail_fail_count
    while True:
        try:
            rows = await asyncio.to_thread(_poll_tail_rows)
            _tail_fail_count = 0
            for row in rows:
                rid = str(row.id)
                if rid in tail_state.seen:
                    continue
                tail_state.seen.add(rid)
                payload = row.payload or {}
                event = payload.get("event")
                data = payload.get("data")
                if row.workspace_id and event:
                    bus.publish(str(row.workspace_id), event, data)
            if len(tail_state.seen) > _SEEN_LIMIT:
                keep = list(tail_state.seen)[-_SEEN_LIMIT:]
                tail_state.seen = set(keep)
            if rows:
                tail_state.last_ts = rows[-1].created_at
                tail_state.last_id = rows[-1].id
        except Exception:
            _tail_fail_count += 1
            if _tail_fail_count == 1 or _tail_fail_count % 60 == 0:
                logger.warning(
                    "SSE tail poll failing (consecutive=%s); suppressing repeats", _tail_fail_count
                )
        await asyncio.sleep(TAIL_POLL_SECONDS)


def ensure_tail_started() -> None:
    """Idempotent start of the single per-process DB tail task."""
    with tail_state.lock:
        if tail_state.task is not None and not tail_state.task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop (e.g. worker-only process); started later
        tail_state.task = loop.create_task(_tail_loop())


@router.get("/stream")
async def events_stream(
    request: Request,
    workspace_id: uuid.UUID,
) -> StreamingResponse:
    """Workspace event stream. Session-cookie auth; no CSRF (GET)."""
    token = request.cookies.get(config.settings.session_cookie_name)
    if not token:
        raise ApiError("authentication_required", "Authentication is required.", 401)
    factory = get_session_factory()
    db = factory()
    try:
        user = resolve_session_user(db, request, token)
        require_workspace_access(workspace_id, "viewer", user, db)
    finally:
        db.close()

    ensure_tail_started()
    queue = bus.subscribe(str(workspace_id))

    def still_authorized():
        with factory() as check_db:
            try:
                current = resolve_session_user(check_db, request, token)
                require_workspace_access(workspace_id, "viewer", current, check_db)
                check_db.commit()
                return True
            except ApiError:
                return False

    async def generator():
        last_auth_check = time.monotonic()
        yield ": connected\nretry: 15000\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                if time.monotonic() - last_auth_check >= 15:
                    if not await asyncio.to_thread(still_authorized):
                        break
                    last_auth_check = time.monotonic()
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield f": ping {int(time.time())}\n\n"
                    continue
                yield format_sse(evt)
        except asyncio.CancelledError:  # client disconnect
            pass
        finally:
            bus.unsubscribe(str(workspace_id), queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
