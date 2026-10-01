"""Consumo de tokens persistente (por día y total), para que sobreviva a los reinicios. Se conservan 60 días."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core.settings import _atomic_write

KEEP_DAYS = 60


def _zero() -> dict:
    return {"calls": 0, "input": 0, "output": 0}


class UsageStore:
    def __init__(self, path: str | Path, today=date.today):
        self.path, self._today = Path(path), today
        self.total, self.days = _zero(), {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self.total = self._clean(d.get("total"))
                self.days = {k: self._clean(v) for k, v in (d.get("days") or {}).items() if isinstance(k, str) and len(k) == 10}
        except (OSError, ValueError, AttributeError):
            pass

    @staticmethod
    def _clean(v) -> dict:
        out = _zero()
        if isinstance(v, dict):
            for k in out:
                x = v.get(k)
                out[k] = x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else 0
        return out

    def add(self, input_tokens: int, output_tokens: int) -> None:
        key = self._today().isoformat()
        for bucket in (self.total, self.days.setdefault(key, _zero())):
            bucket["calls"] += 1
            bucket["input"] += max(0, int(input_tokens))
            bucket["output"] += max(0, int(output_tokens))
        for old in sorted(self.days)[:-KEEP_DAYS]:
            del self.days[old]
        try:
            _atomic_write(self.path, json.dumps({"total": self.total, "days": self.days}))
        except OSError:
            pass                                    # no poder guardar el consumo nunca debe tumbar una llamada al LLM

    def snapshot(self) -> dict:
        return {"today": dict(self.days.get(self._today().isoformat(), _zero())), "total": dict(self.total)}
