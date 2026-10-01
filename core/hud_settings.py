"""Mensajes del HUD para memoria, permisos y auditoría. Cada cambio responde con una instantánea completa por el bus."""
from __future__ import annotations

import asyncio

from core.bus import EventBus
from core.memory import Memory, MemoryError_
from core.permissions import PermissionError_, PermissionStore


class SettingsHandlers:
    def __init__(self, bus: EventBus, audit, memory: Memory, perms: PermissionStore, export_dir=None):
        self.bus, self.audit, self.memory, self.perms = bus, audit, memory, perms
        self.export_dir = export_dir

    def publish_memory(self) -> None:
        self.bus.publish("memory.changed", self.memory.snapshot())

    def publish_permissions(self) -> None:
        self.bus.publish("permissions.changed", self.perms.snapshot())

    def _notice(self, level: str, text: str) -> None:
        self.bus.publish("ui.notice", {"level": level, "text": text})

    async def __call__(self, msg: dict) -> bool:
        kind = msg.get("type")
        if not isinstance(kind, str) or not kind.startswith(("memory.", "permissions.", "audit.")):
            return False
        if kind.startswith("audit."):
            return await self._audit(kind, msg)
        try:
            if kind == "memory.list":
                pass
            elif kind == "memory.add":
                self.memory.add(msg.get("kind"), msg.get("content")); self.audit.append("memory.add", kind=msg.get("kind"))
            elif kind == "memory.update":
                self.memory.update(msg.get("id"), msg.get("content")); self.audit.append("memory.update", id=msg.get("id"))
            elif kind == "memory.delete":
                self.memory.delete(msg.get("id")); self.audit.append("memory.delete", id=msg.get("id"))
            elif kind == "memory.clear_episodes":
                self.memory.clear_episodes(); self.audit.append("memory.clear_episodes")
            elif kind == "permissions.get":
                pass
            elif kind == "permissions.set_confirm":
                self.perms.set_confirm(msg.get("class"), msg.get("value"))
                self.audit.append("permissions.set_confirm", cls=msg.get("class"), value=msg.get("value"))
            elif kind == "permissions.set_tool":
                self.perms.set_tool(msg.get("tool"), msg.get("enabled"))
                self.audit.append("permissions.set_tool", tool=msg.get("tool"), enabled=msg.get("enabled"))
            elif kind == "permissions.add_root":
                self.perms.add_root(msg.get("path")); self.audit.append("permissions.add_root", path=msg.get("path"))
            elif kind == "permissions.remove_root":
                self.perms.remove_root(msg.get("path")); self.audit.append("permissions.remove_root", path=msg.get("path"))
            else:
                return True     # tipo desconocido del mismo espacio: se ignora
        except (MemoryError_, PermissionError_) as e:
            self._notice("error", str(e))
        finally:
            (self.publish_memory if kind.startswith("memory.") else self.publish_permissions)()
        return True

    async def _audit(self, kind: str, msg: dict) -> bool:
        """Solo lectura: consultar y verificar nunca modifican el log (y no se auditan a sí mismas, para no inundarlo)."""
        if kind == "audit.get":
            limit, event, text = msg.get("limit", 200), msg.get("event"), msg.get("text")
            if (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500
                    or not (event is None or (isinstance(event, str) and len(event) <= 60))
                    or not (text is None or (isinstance(text, str) and len(text) <= 100))):
                self._notice("error", "consulta de auditoría inválida")
                return True
            res = await asyncio.to_thread(self.audit.query, limit, event or None, text or None)
            self.bus.publish("audit.changed", {**res, "filters": {"event": event or "", "text": text or "", "limit": limit}})
        elif kind == "audit.export":
            event, text = msg.get("event"), msg.get("text")
            if (self.export_dir is None or not (event is None or (isinstance(event, str) and len(event) <= 60))
                    or not (text is None or (isinstance(text, str) and len(text) <= 100))):
                self._notice("error", "exportación de auditoría inválida")
                return True
            from datetime import datetime
            from pathlib import Path
            dest = Path(self.export_dir) / f"auditoria-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
            n = await asyncio.to_thread(self.audit.export, dest, event or None, text or None)
            self._notice("info", f"{n} registros exportados a {dest}")
        elif kind == "audit.verify":
            res = await asyncio.to_thread(self.audit.verify_detail)       # recorre todo el archivo: fuera del event loop
            self.bus.publish("audit.verified", res)
        return True
