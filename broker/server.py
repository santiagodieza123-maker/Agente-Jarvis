"""Lógica del servidor del broker, independiente del transporte: autentica, valida, pide confirmación humana y ejecuta."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from broker.ops import Operations, describe
from broker.protocol import READ_ONLY_OPS, Authenticator, ProtocolError, parse, validate_args

MAX_PER_MINUTE = 6


class BrokerCore:
    def __init__(self, auth: Authenticator, ops: Operations, approver: Callable[[str, str], bool], log_path: str | Path | None = None,
                 clock: Callable[[], float] = time.time):
        """`approver(op, texto) -> bool`: confirmación humana (diálogo propio del broker). Una a la vez."""
        self.auth, self.ops, self.approver, self.log_path, self.clock = auth, ops, approver, Path(log_path) if log_path else None, clock
        self._asked: list[float] = []
        self.stopping = False

    def _log(self, **rec) -> None:
        if self.log_path is None:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": self.clock(), **rec}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def handle_raw(self, raw: bytes) -> dict:
        rid = "?"
        try:
            req = parse(raw)
            rid = req.get("id") if isinstance(req.get("id"), str) else "?"
            self.auth.check(req)
            op = req["op"]
            args = validate_args(op, req["args"])
            if op == "shutdown":
                self.stopping = True
                self._log(op=op, ok=True)
                return {"id": rid, "ok": True, "result": {"stopping": True}}
            if op not in READ_ONLY_OPS:
                now = self.clock()
                self._asked = [t for t in self._asked if now - t < 60]
                if len(self._asked) >= MAX_PER_MINUTE:
                    raise ProtocolError("demasiadas solicitudes de confirmación por minuto")
                self._asked.append(now)
                if not self.approver(op, describe(op, args)):
                    self._log(op=op, args=args, approved=False)
                    return {"id": rid, "ok": False, "error": "el usuario denegó la operación"}
            result = self.ops.run(op, args)
            self._log(op=op, args=args, approved=True, result={k: (v if k != "output" else str(v)[-300:]) for k, v in result.items()})
            return {"id": rid, "ok": True, "result": result}
        except ProtocolError as e:
            self._log(error=str(e), id=rid)
            return {"id": rid, "ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 — el broker nunca debe caerse por una petición
            self._log(error=f"{type(e).__name__}: {e}", id=rid)
            return {"id": rid, "ok": False, "error": f"error interno: {type(e).__name__}"}
