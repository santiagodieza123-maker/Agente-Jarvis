"""Bus de eventos en proceso. Los eventos siguen schemas/events.schema.json."""
from __future__ import annotations

import asyncio
import time
from typing import Any

VERSION = "0.1.0"
EVENT_TYPES = frozenset({
    "plan.updated", "action.started", "action.finished", "perception.frame",
    "approval.requested", "approval.granted", "approval.denied",
    "memory.changed", "permissions.changed", "config.changed", "audit.changed", "audit.appended", "audit.verified", "ui.notice", "state.changed", "kill.triggered",
})


def make_event(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    if type_ not in EVENT_TYPES:
        raise ValueError(f"tipo de evento desconocido: {type_}")
    return {"v": VERSION, "ts": time.time(), "type": type_, "payload": payload}


class EventBus:
    def __init__(self, maxsize: int = 256):
        self._subs: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self._maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, type_: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        ev = make_event(type_, payload or {})
        for q in self._subs:
            if q.full():  # suscriptor lento: descarta el más antiguo, nunca bloquea al agente
                q.get_nowait()
            q.put_nowait(ev)
        return ev
