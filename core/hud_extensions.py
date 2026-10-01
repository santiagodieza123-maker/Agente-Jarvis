"""Mensajes `extensions.*` del HUD. Cada cambio responde con una instantánea completa por el bus."""
from __future__ import annotations

from core.bus import EventBus
from core.mcp_client import ExtensionError, ExtensionManager
from core.permissions import PermissionError_, PermissionStore


class ExtensionHandlers:
    def __init__(self, bus: EventBus, manager: ExtensionManager, perms: PermissionStore, publish_permissions):
        self.bus, self.mgr, self.perms, self.publish_permissions = bus, manager, perms, publish_permissions

    def publish(self) -> None:
        self.bus.publish("extensions.changed", self.mgr.snapshot())

    def _notice(self, level: str, text: str) -> None:
        self.bus.publish("ui.notice", {"level": level, "text": text})

    async def __call__(self, msg: dict) -> bool:
        kind = msg.get("type")
        if not isinstance(kind, str) or not kind.startswith("extensions."):
            return False
        try:
            if kind == "extensions.add":
                if msg.get("confirmed") is not True:          # el HUD debe haber mostrado el comando exacto al usuario
                    raise ExtensionError("falta la confirmación del usuario")
                await self.mgr.add(msg.get("name"), msg.get("command"), msg.get("env"))
            elif kind == "extensions.remove":
                await self.mgr.remove(msg.get("name"))
            elif kind == "extensions.set_enabled":
                await self.mgr.set_enabled(msg.get("name"), msg.get("enabled"))
            elif kind == "extensions.set_env":
                await self.mgr.set_env(msg.get("name"), msg.get("env"))
            elif kind == "extensions.restart":
                await self.mgr.restart(msg.get("name"))
            elif kind == "extensions.set_trust":
                self.mgr.set_trust(msg.get("name"), msg.get("tool"), msg.get("read"))
            elif kind == "extensions.set_tool":
                self.mgr.set_tool_enabled(msg.get("name"), msg.get("tool"), msg.get("enabled"), self.perms)
                self.publish_permissions()
            elif kind != "extensions.get":
                return True
        except (ExtensionError, PermissionError_) as e:
            self._notice("error", str(e))
        finally:
            self.publish()
        return True
