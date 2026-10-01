"""Log de auditoría JSONL con hash encadenado y, si hay clave, autenticado con HMAC.
Sin clave detecta ediciones, borrados e inserciones parciales. Con clave (guardada fuera del alcance del agente: Credential
Manager o archivo 0600) cada registro lleva `mac = HMAC-SHA256(clave, hash)`: quien reescriba el archivo recalculando la
cadena no puede producir los mac. Un fichero `anchor` (también autenticado) guarda el recuento y la cabecera para detectar
truncados, y un fichero con mac no puede degradarse a uno sin mac."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
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
    def __init__(self, path: str | Path, on_append: Callable[[dict], None] | None = None,
                 key: bytes | None = None, anchor: str | Path | None = None, keyed_before: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.on_append = on_append          # p. ej. publicar el registro al HUD en vivo
        self.key = key
        self.anchor = Path(anchor) if anchor else None
        self._last, has_mac = self._scan()
        self._lines = self._count_lines()    # líneas físicas: `seq` y `bad_line` usan esta misma numeración
        self._suspect: str | None = None
        if key and self._lines and not has_mac:
            if keyed_before or (self.anchor and self.anchor.is_file()):
                # Ya hubo autenticación (ancla o marca en el almacén de secretos) y ahora no hay ni un mac:
                # alguien reescribió el archivo sin ellos. No se "migra": se señala.
                self._suspect = "registros sin autenticar aunque el log ya estaba autenticado"
            else:
                self.append("audit.keyed", migrated=True)   # log anterior a la clave: desde aquí todo queda autenticado
        if key and not self._suspect:
            # Antes de añadir nada: ¿falta algo respecto al ancla? Si sí, queda constancia permanente en el propio log
            # (un registro con mac) y este proceso lo seguirá señalando en verify().
            reason = self._check_anchor(self._lines, self._last)
            if reason:
                self._suspect = reason
                self.append("audit.tamper_detected", reason=reason)

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

    def _scan(self) -> tuple[str, bool]:
        """(hash del último registro válido, ¿hay algún registro con mac?). Una línea corrupta no impide arrancar."""
        if not self.path.exists():
            return GENESIS, False
        last, has_mac = GENESIS, False
        with self.path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                rec = self._parse(line) if line.strip() else None
                if rec:
                    last, has_mac = rec["hash"], has_mac or "mac" in rec
        return last, has_mac

    def _mac(self, text: str) -> str:
        return hmac.new(self.key, text.encode(), hashlib.sha256).hexdigest()

    def _write_anchor(self) -> None:
        if not (self.key and self.anchor):
            return
        a = {"count": self._lines, "head": self._last}
        a["mac"] = self._mac(f"{a['count']}|{a['head']}")
        fd, tmp = tempfile.mkstemp(dir=self.anchor.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(a, f)
        os.replace(tmp, self.anchor)

    def _check_anchor(self, count: int, head: str) -> str | None:
        """Motivo del fallo, o None si el ancla es coherente (o no existe)."""
        if not (self.key and self.anchor and self.anchor.is_file()):
            return None
        try:
            a = json.loads(self.anchor.read_text(encoding="utf-8"))
            n, h, m = a["count"], a["head"], a["mac"]
        except (OSError, ValueError, KeyError, TypeError):
            return "ancla ilegible"
        if not (isinstance(n, int) and isinstance(h, str) and isinstance(m, str) and hmac.compare_digest(m, self._mac(f"{n}|{h}"))):
            return "ancla manipulada"
        if count < n:
            return f"faltan registros (el ancla recuerda {n}, el archivo tiene {count})"
        if count == n and head != h:
            return "el archivo no coincide con el ancla"
        return None

    @property
    def head(self) -> str:
        return self._last

    def append(self, event: str, **data) -> dict:
        body = {"ts": time.time(), "event": event, "data": data}
        rec = {**body, "prev": self._last, "hash": self._digest(self._last, body)}
        if self.key:
            rec["mac"] = self._mac(rec["hash"])
        needs_nl = False
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open("rb") as f:
                f.seek(-1, 2)
                needs_nl = f.read(1) != b"\n"      # línea parcial previa: no pegarse a ella
        with self.path.open("a", encoding="utf-8") as f:
            f.write(("\n" if needs_nl else "") + json.dumps(rec, sort_keys=True) + "\n")
        self._last = rec["hash"]
        self._lines += 1
        self._write_anchor()
        if self.on_append:
            self.on_append({**rec, "seq": self._lines})
        return rec

    def verify_detail(self) -> dict:
        """Recorre TODO el archivo. `bad_line` es el número (desde 1) de la primera línea que rompe la cadena.
        `keyed`: la verificación incluyó los mac (hay clave); `reason`: motivo del fallo cuando no es una línea concreta."""
        prev, count, seen_mac = GENESIS, 0, False
        if self.path.exists():
            with self.path.open(encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    rec = self._parse(line)
                    bad = (rec is None or rec["prev"] != prev or rec["hash"] != self._digest(
                        prev, {k: rec[k] for k in ("ts", "event", "data")}))
                    if not bad and self.key:
                        if "mac" in rec:
                            seen_mac = True
                            bad = not (isinstance(rec["mac"], str) and hmac.compare_digest(rec["mac"], self._mac(rec["hash"])))
                        elif seen_mac:
                            bad = True                      # un registro sin mac después de uno con mac: degradación
                    if bad:
                        return {"ok": False, "count": count, "bad_line": n, "head": prev, "keyed": bool(self.key), "reason": None}
                    prev, count = rec["hash"], count + 1
        keyed = bool(self.key)
        if self._suspect:
            return {"ok": False, "count": count, "bad_line": None, "head": prev, "keyed": True, "reason": self._suspect}
        if keyed and count and not seen_mac:
            return {"ok": False, "count": count, "bad_line": None, "head": prev, "keyed": True, "reason": "ningún registro autenticado"}
        reason = self._check_anchor(count, prev)
        return {"ok": reason is None, "count": count, "bad_line": None, "head": prev, "keyed": keyed, "reason": reason}

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
