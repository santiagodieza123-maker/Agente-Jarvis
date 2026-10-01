"""Ensamblado del núcleo: LLM + herramientas + política + auditoría + bus + HUD."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from core.audit import AuditLog, clip
from core.bus import EventBus
from core.hud_config import ConfigHandlers
from core.broker_client import BrokerClient
from core.hud_broker import BrokerHandlers
from core.hud_extensions import ExtensionHandlers
from core.hud_handlers import HudHandlers
from core.hud_recipes import RecipeHandlers
from core.hud_voice import VoiceHandlers
from core.hud_settings import SettingsHandlers
from core.mcp_client import ExtensionManager
from core.memory import Memory
from core.permissions import REPO, PermissionStore
from core.llm.holder import LLMHolder
from core.llm.provider import LLMProvider
from core.orchestrator import Orchestrator
from core.policy import Policy
from core.sensitive import sensitive_hits
from core.usage import UsageStore
from core.settings import DEFAULTS, SecretStore, SettingsStore
from core.tools_fs import FsTools
from core.tools_elevated import ElevatedTools
from core.tools_gui import GuiTools
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


AUTO_BROKER = object()       # wire(..., broker_client=AUTO_BROKER): cliente del broker en Windows; None = sin herramientas elevated
AUTO_GUI = object()          # wire(..., gui_backend=AUTO_GUI): UI Automation si estamos en Windows y está instalado; None = sin herramientas gui


def default_gui_backend():
    if os.name != "nt":
        return None
    try:
        from perception.uia import UIABackend
        return UIABackend()
    except Exception:           # uiautomation/comtypes ausentes: el resto de Jarvis funciona sin las herramientas gui
        return None


FROM_CONFIG = object()      # wire(FROM_CONFIG, ...): el proveedor sale de los ajustes del HUD y de la clave guardada o del entorno


def build_llm(model: str, key: str | None) -> LLMProvider | None:
    if not key:
        return None
    from core.llm.gemini import GeminiProvider
    return GeminiProvider(key, model)


def wire(llm, bus: EventBus, audit: AuditLog, roots: list[Path],
         exit_fn=os._exit, approval_timeout: float = 120.0, home: Path | None = None, gui_backend=AUTO_GUI, broker_client=AUTO_BROKER, broker_launch=None) -> HudHandlers:
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
    gui = default_gui_backend() if gui_backend is AUTO_GUI else gui_backend
    gui_tools = GuiTools(gui, on_frame=lambda f: bus.publish("perception.frame", f)).tools() if gui is not None else []
    broker = (BrokerClient(home) if os.name == "nt" else None) if broker_client is AUTO_BROKER else broker_client
    elevated_tools = ElevatedTools(broker).tools() if broker is not None else []
    tools = {t.name: t for t in (*fs.tools(), *shell.tools(), *web.tools(), *gui_tools, *elevated_tools)}
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

    holder = LLMHolder(None if llm is FROM_CONFIG else llm, UsageStore(home / "usage.json"))
    timeout = {"v": float(cfg.values["approval_timeout"])}

    async def approver(approval_id, action, args) -> bool:
        return await handlers.request(approval_id, timeout["v"])

    orch = Orchestrator(holder, tools, policy, audit, bus, approver,
                        is_enabled=lambda n: n not in perms.disabled, memory_block=memory.prompt_block,
                        workdir=lambda: perms.roots[0] if perms.roots else None,
                        sensitive=lambda tool, args: sensitive_hits(tool, args, [home, REPO / ".env"]),
                        external_context=lambda: cfg.values["confirm_with_extensions"] and any(
                            n.startswith("mcp.") and n not in perms.disabled for n in tools))

    def components() -> list[dict]:
        """Salud de cada pieza para el panel SISTEMA."""
        import psutil
        comps = [{"name": "núcleo", "state": "ok", "detail": f"pid {os.getpid()}"},
                 {"name": "modelo", "state": "ok" if holder.inner is not None else "sin clave", "detail": getattr(holder.inner, "model", "")},
                 {"name": "navegador", "state": "ok" if web._page is not None else "inactivo", "detail": "perfil propio · proxy de salida"},
                 {"name": "UI Automation", "state": "ok" if gui is not None else "no disponible", "detail": "" if gui is not None else "solo en Windows con uiautomation"}]
        try:
            parent = psutil.Process(os.getpid()).parent()
            under = parent is not None and any("watchdog" in a for a in parent.cmdline())
        except psutil.Error:
            under = False
        comps.append({"name": "watchdog", "state": "ok" if under else "aviso", "detail": "Ctrl+Shift+F10 activo" if under else "el núcleo corre sin watchdog"})
        comps += [{"name": f"mcp:{e.name}", "state": {"running": "ok", "starting": "arrancando", "stopped": "inactivo"}.get(e.state, e.state), "detail": e.error[:80]}
                  for e in manager.exts.values()]
        return comps
    handlers.components = components
    handlers.extra.append(VoiceHandlers(bus, audit, holder))
    handlers.extra.append(BrokerHandlers(bus, audit, broker, home, broker_launch))
    handlers.extra.append(RecipeHandlers(bus, audit, memory, orch, handlers, tools, lambda n: n not in perms.disabled,
                                         policy._path_allowed, settings.publish_memory))

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
        loop = asyncio.get_running_loop()
        holder.on_wait = lambda secs, why: loop.call_soon_threadsafe(     # se llama desde el hilo del LLM
            bus.publish, "plan.updated", {"text": f"Esperando por {why} ({int(secs)} s)…"})
        try:
            final = await orch.run(goal)
        finally:
            config.publish()                      # refresca el consumo de tokens
        memory.record_episode(goal, final["status"], final["steps"], final["answer"], final["calls"], final["tainted"])
        settings.publish_memory()

    handlers.run_task = run_task
    return handlers
