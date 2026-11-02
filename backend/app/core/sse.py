"""In-process SSE event bus.

Workspace-scoped realtime updates (API_SPECIFICATION.md section 15). Events
are ephemeral: clients refetch canonical resources after reconnect. A DB
tail in the SSE handler covers events produced by other processes.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SseEvent:
    workspace_id: str
    event: str
    data: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[SseEvent]]] = {}

    def subscribe(self, workspace_id: str) -> asyncio.Queue[SseEvent]:
        q: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=200)
        self._queues.setdefault(workspace_id, []).append(q)
        return q

    def unsubscribe(self, workspace_id: str, q: asyncio.Queue[SseEvent]) -> None:
        lst = self._queues.get(workspace_id)
        if lst and q in lst:
            lst.remove(q)
            if not lst:
                self._queues.pop(workspace_id, None)

    def publish(self, workspace_id: str, event: str, data: dict[str, Any]) -> None:
        evt = SseEvent(workspace_id=workspace_id, event=event, data=data)
        for q in list(self._queues.get(workspace_id, [])):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:  # slow consumer drops the update
                pass


bus = EventBus()


def format_sse(evt: SseEvent) -> str:
    return (
        f"event: {evt.event}\n"
        f"id: {evt.id}\n"
        f'data: {json.dumps(evt.data, default=str)}\n\n'
    )
