"""Permisos configurables y persistentes: confirmación por clase, herramientas habilitadas y raíces de archivos.
Solo se modifican desde el HUD (canal autenticado); ninguna herramienta del agente puede tocarlos.
Las clases DESTRUCTIVE/ELEVATED están bloqueadas: siempre piden confirmación."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from core.policy import LOCKED_CLASSES, ActionClass, Policy

REPO = Path(__file__).resolve().parent.parent
_SYSTEM_DIRS_POSIX = ("/etc", "/usr", "/bin", "/sbin", "/var", "/boot", "/dev", "/proc", "/sys", "/lib", "/root/.ssh")


class PermissionError_(ValueError):
    pass


class PermissionStore:
    def __init__(self, path: str | Path, policy: Policy, fs, default_roots: list[Path], tools: dict,
                 protected: list[Path] | None = None):
        self.path, self.policy, self.fs, self.tools = Path(path), policy, fs, tools
        # Carpetas que ninguna raíz puede contener ni estar dentro: el repo (.env con la clave) y la config de Jarvis.
        self.protected = [p.resolve() for p in (protected or [REPO, self.path.parent])]
        self.roots: list[Path] = [r.resolve() for r in default_roots]
        self.disabled: set[str] = set()
        self._load()
        self._apply()

    # --- persistencia ---
    def _load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(d.get("roots"), list):
            roots = []
            for r in d["roots"]:
                try:
                    roots.append(self._validate_root(r, must_exist=False))
                except PermissionError_:
                    pass            # raíz guardada que ya no es válida: se descarta
            self.roots = roots
        for k, v in (d.get("confirm") or {}).items():
            if k in ActionClass._value2member_map_ and ActionClass(k) not in LOCKED_CLASSES and isinstance(v, bool):
                self.policy.confirm[ActionClass(k)] = v
        self.disabled = {t for t in (d.get("disabled") or []) if isinstance(t, str) and t in self.tools}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"roots": [str(r) for r in self.roots], "disabled": sorted(self.disabled),
                "confirm": {c.value: v for c, v in self.policy.confirm.items() if c not in LOCKED_CLASSES}}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)          # escritura atómica

    def _apply(self) -> None:
        self.policy.allowed_roots[:] = [str(r) for r in self.roots]
        self.fs.roots[:] = list(self.roots)

    # --- validación ---
    def _validate_root(self, raw: object, must_exist: bool = True) -> Path:
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 500:
            raise PermissionError_("ruta inválida")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            raise PermissionError_("la ruta debe ser absoluta")
        p = p.resolve()
        if must_exist and not p.is_dir():
            raise PermissionError_("la carpeta no existe")
        if len(p.parts) <= 1 or p == Path.home():
            raise PermissionError_("demasiado amplia: elige una subcarpeta concreta")
        if os.name == "nt":
            low = str(p).lower()
            bad = [os.environ.get(v, "").lower() for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")]
            if any(b and (low == b or low.startswith(b + os.sep)) for b in bad):
                raise PermissionError_("carpeta del sistema")
        elif any(p == Path(d) or Path(d) in p.parents for d in _SYSTEM_DIRS_POSIX):
            raise PermissionError_("carpeta del sistema")
        for prot in self.protected:
            if p == prot or prot in p.parents or p in prot.parents:
                raise PermissionError_("contiene o está dentro de la carpeta de Jarvis (secretos y configuración)")
        return p

    # --- operaciones (todas persisten y reaplican) ---
    def set_confirm(self, cls_name: object, value: object) -> None:
        if cls_name not in ActionClass._value2member_map_:
            raise PermissionError_(f"clase desconocida: {cls_name!r}")
        cls = ActionClass(cls_name)
        if cls in LOCKED_CLASSES:
            raise PermissionError_(f"'{cls.value}' siempre exige confirmación y no se puede relajar")
        if not isinstance(value, bool):
            raise PermissionError_("valor inválido")
        self.policy.confirm[cls] = value
        self._save()

    def set_tool(self, name: object, enabled: object) -> None:
        if not isinstance(name, str) or name not in self.tools:
            raise PermissionError_(f"herramienta desconocida: {name!r}")
        if not isinstance(enabled, bool):
            raise PermissionError_("valor inválido")
        (self.disabled.discard if enabled else self.disabled.add)(name)
        self._save()

    def add_root(self, raw: object) -> None:
        p = self._validate_root(raw)
        if p not in self.roots:
            if len(self.roots) >= 20:
                raise PermissionError_("máximo 20 carpetas")
            self.roots.append(p)
            self._apply(); self._save()

    def remove_root(self, raw: object) -> None:
        p = Path(str(raw)).expanduser().resolve()
        if p in self.roots:
            self.roots.remove(p)
            self._apply(); self._save()

    def snapshot(self) -> dict:
        return {
            "classes": [{"name": c.value, "confirm": c in LOCKED_CLASSES or self.policy.confirm[c], "locked": c in LOCKED_CLASSES}
                        for c in ActionClass],
            "tools": [{"name": t.name, "cls": t.cls.value, "enabled": t.name not in self.disabled,
                       "description": t.description} for t in self.tools.values()],
            "roots": [str(r) for r in self.roots],
        }
