"""Manejo de mensajes HUD -> core: pánico, tareas y aprobaciones."""
from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable

from core.audit import AuditLog
from core.bus import EventBus

TaskRunner = Callable[[str], Awaitable[None]]


class HudHandlers:
    def __init__(self, bus: EventBus, audit: AuditLog, exit_fn: Callable[[int], None] = os._exit,
                 run_task: TaskRunner | None = None):
        self.bus, self.audit, self.exit_fn, self.run_task = bus, audit, exit_fn, run_task
        self._pending: dict[str, asyncio.Future] = {}
        self._task: asyncio.Task | None = None

    async def __call__(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "panic":
            await self.panic()
        elif kind == "approval":
            fut = self._pending.get(str(msg.get("id")))
            if fut and not fut.done():
                fut.set_result(msg.get("granted") is True)   # estrictamente True; cualquier otra cosa deniega
        elif kind == "task":
            await self._start_task(str(msg.get("goal", ""))[:2000])

    async def _start_task(self, goal: str) -> None:
        self.audit.append("task.received", goal=goal)
        if self.run_task is None:
            self.bus.publish("plan.updated", {"text": "Núcleo sin proveedor LLM configurado: tarea registrada, no ejecutada."})
            self.bus.publish("state.changed", {"state": "idle"})
            return
        if self._task and not self._task.done():
            self.bus.publish("plan.updated", {"text": "Ya hay una tarea en curso; espera a que termine."})
            return
        self._task = asyncio.create_task(self._guarded(goal))

    async def _guarded(self, goal: str) -> None:
        try:
            await self.run_task(goal)
        except Exception as e:  # un fallo del planificador no debe tumbar el núcleo
            self.audit.append("task.crashed", error=f"{type(e).__name__}: {e}")
            self.bus.publish("plan.updated", {"text": f"La tarea falló: {type(e).__name__}"})
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
