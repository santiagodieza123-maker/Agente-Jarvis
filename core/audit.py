"""Log de auditoría JSONL con hash encadenado.
Detecta ediciones, borrados e inserciones parciales. NO protege contra quien reescriba todo el archivo recalculando
la cadena entera (no hay clave): para eso, anota el hash de cabecera (`head`) que muestra el HUD en un lugar aparte."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

GENESIS = "0" * 64
MAX_READ_BYTES = 5_000_000      # al consultar solo se lee el final del archivo


def clip(rec: dict, max_chars: int = 2000) -> dict:
    """Copia para mostrar en el HUD: si `data` es enorme (p. ej. el contenido de un archivo escrito) se recorta.
    El log en disco conserva el registro completo."""
    raw = json.dumps(rec["data"], ensure_ascii=False)
    if len(raw) <= max_chars:
        return rec
    return {**rec, "data": {"recortado": raw[:max_chars] + "…"}, "clipped": True}


class AuditLog:
    def __init__(self, path: str | Path, on_append: Callable[[dict], None] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.on_append = on_append          # p. ej. publicar el registro al HUD en vivo
        self._last = self._tail_hash()
        self._lines = self._count_lines()    # líneas físicas: `seq` y `bad_line` usan esta misma numeración

    def _count_lines(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("rb") as f:
            return sum(1 for _ in f)

    @staticmethod
    def _digest(prev: str, body: dict) -> str:
        data = prev + json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def _parse(line: str) -> dict | None:
        """Registro bien formado o None (JSON roto, tipos inesperados o campos ausentes)."""
        try:
            rec = json.loads(line)
        except ValueError:
            return None
        if (not isinstance(rec, dict) or not isinstance(rec.get("hash"), str) or not isinstance(rec.get("prev"), str)
                or not isinstance(rec.get("event"), str) or not isinstance(rec.get("data"), dict)
                or not isinstance(rec.get("ts"), (int, float))):
            return None
        return rec

    def _tail_hash(self) -> str:
        """Hash del último registro válido; una línea corrupta no impide arrancar (verify() la señalará)."""
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                rec = self._parse(line) if line.strip() else None
                if rec:
                    last = rec["hash"]
        return last

    @property
    def head(self) -> str:
        return self._last

    def append(self, event: str, **data) -> dict:
        body = {"ts": time.time(), "event": event, "data": data}
        rec = {**body, "prev": self._last, "hash": self._digest(self._last, body)}
        needs_nl = False
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open("rb") as f:
                f.seek(-1, 2)
                needs_nl = f.read(1) != b"\n"      # línea parcial previa: no pegarse a ella
        with self.path.open("a", encoding="utf-8") as f:
            f.write(("\n" if needs_nl else "") + json.dumps(rec, sort_keys=True) + "\n")
        self._last = rec["hash"]
        self._lines += 1
        if self.on_append:
            self.on_append({**rec, "seq": self._lines})
        return rec

    def verify_detail(self) -> dict:
        """Recorre TODO el archivo. `bad_line` es el número (desde 1) de la primera línea que rompe la cadena."""
        prev, count = GENESIS, 0
        if not self.path.exists():
            return {"ok": True, "count": 0, "bad_line": None, "head": prev}
        with self.path.open(encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = self._parse(line)
                if rec is None or rec["prev"] != prev or rec["hash"] != self._digest(
                        prev, {k: rec[k] for k in ("ts", "event", "data")}):
                    return {"ok": False, "count": count, "bad_line": n, "head": prev}
                prev, count = rec["hash"], count + 1
        return {"ok": True, "count": count, "bad_line": None, "head": prev}

    def verify(self) -> bool:
        return self.verify_detail()["ok"]

    def query(self, limit: int = 200, event: str | None = None, text: str | None = None) -> dict:
        """Registros más recientes primero. `seq` es el número de línea. Lee solo el final del archivo."""
        records: list[dict] = []
        seen: set[str] = set()
        truncated, total = False, 0
        if self.path.exists():
            size = self.path.stat().st_size
            with self.path.open("rb") as f:
                start = max(0, size - MAX_READ_BYTES)
                truncated = start > 0
                f.seek(start)
                raw = f.read()
            lines = raw.decode("utf-8", errors="replace").split("\n")
            if lines and lines[-1] == "":
                lines.pop()                     # el archivo termina en salto de línea
            if truncated:
                lines = lines[1:]               # la primera línea puede estar cortada
            all_lines = sum(1 for _ in self.path.open("rb")) if truncated else len(lines)
            first = all_lines - len(lines) + 1
            needle = text.lower() if text else None
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                rec = self._parse(line)
                if rec is None:
                    rec = {"event": "(línea corrupta)", "ts": 0, "data": {"raw": line[:200]}, "prev": "", "hash": ""}
                total += 1
                seen.add(rec["event"])
                if event and rec["event"] != event:
                    continue
                if needle and needle not in json.dumps(rec["data"], ensure_ascii=False).lower() and needle not in rec["event"].lower():
                    continue
                records.append(clip({**rec, "seq": first + i}))
        return {"records": records[::-1][:limit], "matched": len(records), "total": total, "event_types": sorted(seen),
                "head": self._last, "truncated": truncated}
