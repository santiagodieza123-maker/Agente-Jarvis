"""Log de auditoría JSONL con hash encadenado (detecta manipulación posterior)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last = self._tail_hash()

    def _tail_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    @staticmethod
    def _digest(prev: str, body: dict) -> str:
        data = prev + json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()

    def append(self, event: str, **data) -> dict:
        body = {"ts": time.time(), "event": event, "data": data}
        rec = {**body, "prev": self._last, "hash": self._digest(self._last, body)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self._last = rec["hash"]
        return rec

    def verify(self) -> bool:
        prev = GENESIS
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                body = {k: rec[k] for k in ("ts", "event", "data")}
                if rec["prev"] != prev or rec["hash"] != self._digest(prev, body):
                    return False
                prev = rec["hash"]
        return True
