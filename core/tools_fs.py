"""Herramientas de archivos acotadas a raíces permitidas. Resuelven rutas reales (symlinks, '..') antes de operar."""
from __future__ import annotations

from pathlib import Path

from core.orchestrator import Tool
from core.policy import ActionClass

MAX_READ = 20_000


class FsTools:
    def __init__(self, roots: list[str | Path]):
        self.roots = [Path(r).resolve() for r in roots]

    def _safe(self, path: str) -> Path:
        p = Path(path).resolve()
        if not any(p == r or r in p.parents for r in self.roots):
            raise PermissionError(f"ruta fuera de las raíces permitidas: {path}")
        return p

    def read(self, path: str) -> str:
        return self._safe(path).read_text(encoding="utf-8", errors="replace")[:MAX_READ]

    def list(self, path: str) -> str:
        return "\n".join(sorted(c.name + ("/" if c.is_dir() else "") for c in self._safe(path).iterdir()))

    def write(self, path: str, content: str) -> str:
        p = self._safe(path)
        p.write_text(content, encoding="utf-8")
        return f"escrito {len(content)} caracteres en {p}"

    def delete(self, path: str) -> str:
        p = self._safe(path)
        if p.is_dir():
            raise IsADirectoryError("solo se borran archivos")
        p.unlink()
        return f"borrado {p}"

    def tools(self) -> list[Tool]:
        # El contenido de archivos puede venir de terceros: salida marcada como no confiable.
        return [
            Tool("fs.read", ActionClass.READ, self.read, "Lee un archivo de texto (path)", True, "path"),
            Tool("fs.list", ActionClass.READ, self.list, "Lista un directorio (path)", True, "path"),
            Tool("fs.write", ActionClass.WRITE_REVERSIBLE, self.write, "Escribe un archivo (path, content)", False, "path"),
            Tool("fs.delete", ActionClass.DESTRUCTIVE, self.delete, "Borra un archivo (path)", False, "path"),
        ]
