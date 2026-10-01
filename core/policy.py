"""Motor de políticas: clasifica acciones y decide si se permiten, requieren confirmación o se deniegan."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePath


class ActionClass(str, Enum):
    READ = "read"
    WRITE_REVERSIBLE = "write_reversible"
    DESTRUCTIVE = "destructive"
    ELEVATED = "elevated"


class Decision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class Origin(str, Enum):
    USER = "user"            # instrucción directa del usuario
    OBSERVED = "observed"    # contenido leído de web/correo/PDF/pantalla: NO confiable


@dataclass(frozen=True)
class Action:
    tool: str
    cls: ActionClass
    origin: Origin
    path: str | None = None


@dataclass
class Policy:
    allowed_roots: list[str] = field(default_factory=list)
    # nivel de confirmación por clase: True = pide confirmación humana
    confirm: dict[ActionClass, bool] = field(default_factory=lambda: {
        ActionClass.READ: False,
        ActionClass.WRITE_REVERSIBLE: False,
        ActionClass.DESTRUCTIVE: True,
        ActionClass.ELEVATED: True,
    })

    def _path_allowed(self, path: str) -> bool:
        p = PurePath(path)
        if ".." in p.parts:
            return False
        return any(p == PurePath(r) or PurePath(r) in p.parents for r in self.allowed_roots)

    def evaluate(self, a: Action) -> Decision:
        if a.path is not None and not self._path_allowed(a.path):
            return Decision.DENY
        # Contenido no confiable nunca origina acciones que modifican estado por sí solo.
        if a.origin is Origin.OBSERVED and a.cls is not ActionClass.READ:
            return Decision.CONFIRM if a.cls is not ActionClass.ELEVATED else Decision.DENY
        return Decision.CONFIRM if self.confirm[a.cls] else Decision.ALLOW
