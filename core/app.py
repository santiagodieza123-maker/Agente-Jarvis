"""Ensamblado del núcleo: LLM + herramientas + política + auditoría + bus + HUD."""
from __future__ import annotations

import os
from pathlib import Path

from core.audit import AuditLog, clip
from core.bus import EventBus
from core.hud_config import ConfigHandlers
from core.hud_extensions import ExtensionHandlers
from core.hud_handlers import HudHandlers
from core.hud_settings import SettingsHandlers
from core.mcp_client import ExtensionManager
from core.memory import Memory
from core.permissions import REPO, PermissionStore
from core.llm.holder import LLMHolder
from core.llm.provider import LLMProvider
from core.orchestrator import Orchestrator
from core.policy import Policy
from core.sensitive import sensitive_hits
from core.settings import DEFAULTS, SecretStore, SettingsStore
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


def jarvis_home() -> Path:
    """Configuración persistente (permisos, memoria, perfil del navegador). Sobreescribible con JARVIS_HOME."""
    return Path(os.environ.get("JARVIS_HOME", str(Path.home() / ".jarvis")))


FROM_CONFIG = object()      # wire(FROM_CONFIG, ...): el proveedor sale de los ajustes del HUD y de la clave guardada o del entorno


def build_llm(model: str, key: str | None) -> LLMProvider | None:
    if not key:
        return None
    from core.llm.gemini import GeminiProvider
    return GeminiProvider(key, model)


def wire(llm, bus: EventBus, audit: AuditLog, roots: list[Path],
         exit_fn=os._exit, approval_timeout: float = 120.0, home: Path | None = None) -> HudHandlers:
    home = home or jarvis_home()
    audit.on_append = lambda rec: bus.publish("audit.appended", clip(rec))     # el HUD ve el log en vivo
    handlers = HudHandlers(bus, audit, exit_fn=exit_fn)
    cfg = SettingsStore(home / "settings.json", {
        "approval_timeout": approval_timeout,
        "model": os.environ.get("JARVIS_GEMINI_MODEL", DEFAULTS["model"]),
        "browser_headed": os.environ.get("JARVIS_BROWSER_HEADED") == "1"})
    fs = FsTools(roots)
    shell = ShellTools(roots[0])
    web = WebTools(os.environ.get("JARVIS_BROWSER_PROFILE", str(home / "browser-profile")),
                   headless=not cfg.values["browser_headed"])   # perfil dedicado, nunca el del usuario
    tools = {t.name: t for t in (*fs.tools(), *shell.tools(), *web.tools())}
    policy = Policy(allowed_roots=[str(r.resolve()) for r in roots])
    memory = Memory(home / "memory.db")
    perms = PermissionStore(home / "permissions.json", policy, fs, roots, tools, protected=[REPO, home])
    settings = SettingsHandlers(bus, audit, memory, perms, export_dir=home / "exports")
    handlers.extra.append(settings)
    manager = ExtensionManager(home / "extensions.json", tools, audit, lambda: ext_handlers.publish(),
                               lambda: perms.disabled, roots[0], home / "ext-logs", secrets=SecretStore(home / "secrets.json"))
    ext_handlers = ExtensionHandlers(bus, manager, perms, settings.publish_permissions)
    handlers.extra.append(ext_handlers)
    handlers.panic_hooks = [shell.kill_all, web.close, manager.stop_all]
    handlers.extensions = manager
    handlers.memory, handlers.perms, handlers.settings = memory, perms, settings

    holder = LLMHolder(None if llm is FROM_CONFIG else llm)
    timeout = {"v": float(cfg.values["approval_timeout"])}

    async def approver(approval_id, action, args) -> bool:
        return await handlers.request(approval_id, timeout["v"])

    orch = Orchestrator(holder, tools, policy, audit, bus, approver,
                        is_enabled=lambda n: n not in perms.disabled, memory_block=memory.prompt_block,
                        workdir=lambda: perms.roots[0] if perms.roots else None,
                        sensitive=lambda tool, args: sensitive_hits(tool, args, [home, REPO / ".env"]),
                        external_context=lambda: cfg.values["confirm_with_extensions"] and any(
                            n.startswith("mcp.") and n not in perms.disabled for n in tools))

    def apply(rebuild: bool) -> None:
        """Aplica en caliente los ajustes; rebuild=True recrea el proveedor (cambio de modelo o de clave)."""
        orch.max_steps, orch.max_failures = cfg.values["max_steps"], cfg.values["max_failures"]
        orch.token_budget, timeout["v"] = cfg.values["token_budget"], float(cfg.values["approval_timeout"])
        if rebuild:
            holder.inner = build_llm(cfg.values["model"], config.key())

    config = ConfigHandlers(bus, audit, cfg, SecretStore(home / "secrets.json"), holder, apply)
    handlers.extra.append(config)
    handlers.config = config
    orch.max_steps, orch.max_failures, orch.token_budget = cfg.values["max_steps"], cfg.values["max_failures"], cfg.values["token_budget"]
    if llm is FROM_CONFIG:
        holder.inner = build_llm(cfg.values["model"], config.key())

    async def run_task(goal: str) -> None:
        if holder.inner is None:
            bus.publish("plan.updated", {"text": "Sin clave de API: configúrala en la pestaña CONFIG."})
            bus.publish("state.changed", {"state": "idle"})
            return
        try:
            final = await orch.run(goal)
        finally:
            config.publish()                      # refresca el consumo de tokens
        memory.record_episode(goal, final["status"], final["steps"], final["answer"])
        settings.publish_memory()

    handlers.run_task = run_task
    return handlers
