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
from core.tools_shell import ShellTools
from core.tools_web import WebTools


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
    shell = ShellTools(roots[0])
    web = WebTools(os.environ.get("JARVIS_BROWSER_PROFILE", str(Path.home() / ".jarvis" / "browser-profile")),
                   headless=os.environ.get("JARVIS_BROWSER_HEADED") != "1")   # perfil dedicado, nunca el del usuario
    tools = {t.name: t for t in (*fs.tools(), *shell.tools(), *web.tools())}

    async def approver(approval_id, action, args) -> bool:
        return await handlers.request(approval_id, approval_timeout)

    orch = Orchestrator(llm, tools, Policy(allowed_roots=[str(r.resolve()) for r in roots]),
                        audit, bus, approver)

    async def run_task(goal: str) -> None:
        await orch.run(goal)

    handlers.run_task = run_task
    return handlers


def load_llm() -> LLMProvider | None:
    """Gemini si hay GEMINI_API_KEY (env o .env); modelo sobreescribible con JARVIS_GEMINI_MODEL."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    from core.llm.gemini import DEFAULT_MODEL, GeminiProvider
    return GeminiProvider(key, os.environ.get("JARVIS_GEMINI_MODEL", DEFAULT_MODEL))
