"""Manejo de mensajes HUD -> core: pánico, tareas y aprobaciones."""
from __future__ import annotations

import asyncio
import os
from typing import Callable

from core.audit import AuditLog
from core.bus import EventBus


class HudHandlers:
    def __init__(self, bus: EventBus, audit: AuditLog, exit_fn: Callable[[int], None] = os._exit):
        self.bus, self.audit, self.exit_fn = bus, audit, exit_fn
        self._pending: dict[str, asyncio.Future] = {}

    async def __call__(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "panic":
            await self.panic()
        elif kind == "approval":
            fut = self._pending.get(str(msg.get("id")))
            if fut and not fut.done():
                fut.set_result(bool(msg.get("granted")))
        elif kind == "task":
            goal = str(msg.get("goal", ""))[:2000]
            self.audit.append("task.received", goal=goal)
            # Aún no hay proveedor LLM ni herramientas reales conectados.
            self.bus.publish("plan.updated", {"text": "Núcleo sin proveedor LLM configurado: tarea registrada, no ejecutada."})
            self.bus.publish("state.changed", {"state": "idle"})

    async def panic(self) -> None:
        self.audit.append("kill.triggered", source="hud")
        self.bus.publish("kill.triggered", {"source": "hud"})
        await asyncio.sleep(0.15)  # deja salir el evento hacia el HUD
        # Al salir el núcleo, el watchdog (Job Object KILL_ON_JOB_CLOSE) elimina a todos los hijos.
        self.exit_fn(1)

    async def request(self, approval_id: str, timeout: float = 120.0) -> bool:
        """Espera la decisión del HUD; sin respuesta en `timeout` s se deniega."""
        fut = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(approval_id, None)
