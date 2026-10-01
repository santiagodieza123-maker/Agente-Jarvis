"""Ensamblado del núcleo: LLM + herramientas + política + auditoría + bus + HUD."""
from __future__ import annotations

import os
from pathlib import Path

from core.audit import AuditLog
from core.bus import EventBus
from core.hud_handlers import HudHandlers
from core.llm.provider import LLMProvider
from core.orchestrator import Orchestrator
from core.policy import Policy
from core.tools_fs import FsTools


def workspace_roots() -> list[Path]:
    """Raíces donde el agente puede operar. Por defecto ~/Jarvis; sobreescribible con JARVIS_ROOTS (separadas por ';')."""
    env = os.environ.get("JARVIS_ROOTS")
    roots = [Path(r) for r in env.split(";") if r] if env else [Path.home() / "Jarvis"]
    for r in roots:
        r.mkdir(parents=True, exist_ok=True)
    return roots


def wire(llm: LLMProvider | None, bus: EventBus, audit: AuditLog, roots: list[Path],
         exit_fn=os._exit, approval_timeout: float = 120.0) -> HudHandlers:
    handlers = HudHandlers(bus, audit, exit_fn=exit_fn)
    if llm is None:
        return handlers
    fs = FsTools(roots)

    async def approver(approval_id, action, args) -> bool:
        return await handlers.request(approval_id, approval_timeout)

    orch = Orchestrator(llm, {t.name: t for t in fs.tools()}, Policy(allowed_roots=[str(r.resolve()) for r in roots]),
                        audit, bus, approver)

    async def run_task(goal: str) -> None:
        await orch.run(goal)

    handlers.run_task = run_task
    return handlers


def load_llm() -> LLMProvider | None:
    """Proveedor LLM configurado. Pendiente: implementación Gemini (requiere clave y verificar el ID del modelo)."""
    return None
