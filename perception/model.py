"""Modelo común de lo que ve el agente: ventanas y elementos numerados (el LLM elige por número, nunca por coordenadas)."""
from __future__ import annotations

from dataclasses import dataclass, field

Rect = tuple[int, int, int, int]          # izquierda, arriba, derecha, abajo (píxeles físicos del escritorio virtual)

# roles de elemento que se ofrecen al modelo (los demás son estructura)
INTERACTIVE = {"button", "checkbox", "radiobutton", "edit", "combobox", "listitem", "menuitem", "tabitem", "hyperlink",
               "treeitem", "slider", "splitbutton", "spinner", "dataitem"}
READABLE = {"text", "document"}


@dataclass
class WindowInfo:
    handle: int
    title: str
    process: str = ""
    pid: int = 0
    rect: Rect = (0, 0, 0, 0)
    foreground: bool = False


@dataclass
class Element:
    id: int
    name: str
    role: str
    rect: Rect
    enabled: bool = True
    value: str | None = None          # contenido de campos de texto (nunca de contraseñas)
    checked: bool | None = None
    automation_id: str = ""
    depth: int = 0
    secret: bool = False              # campo de contraseña: no se lee ni se rellena

    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return (l + r) // 2, (t + b) // 2

    @property
    def interactive(self) -> bool:
        return self.role in INTERACTIVE


@dataclass
class Snapshot:
    seq: int
    window: WindowInfo
    elements: list[Element] = field(default_factory=list)
    truncated: bool = False

    def get(self, element_id) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)

    def describe(self, limit_value: int = 80) -> str:
        w = self.window
        lines = [f'VENTANA "{w.title}" ({w.process}) observación #{self.seq}']
        for e in self.elements:
            bits = [f"[{e.id}] {e.role}"]
            if e.name:
                bits.append(f'"{e.name[:80]}"')
            elif e.automation_id:
                bits.append(f"<{e.automation_id}>")
            if e.value is not None and not e.secret:
                bits.append(f'valor="{e.value[:limit_value]}"')
            if e.secret:
                bits.append("(contraseña: no accesible)")
            if e.checked is not None:
                bits.append("marcado" if e.checked else "sin marcar")
            if not e.enabled:
                bits.append("(deshabilitado)")
            lines.append(" ".join(bits))
        if self.truncated:
            lines.append("… (hay más elementos; acota con una ventana concreta)")
        return "\n".join(lines)


def diff_summary(before: Snapshot | None, after: Snapshot) -> str:
    """Qué cambió tras una acción: el postcondición observable que ve el modelo."""
    if before is None:
        return "sin referencia previa"
    if before.window.handle != after.window.handle or before.window.title != after.window.title:
        return f'cambió la ventana: "{before.window.title}" -> "{after.window.title}"'
    key = lambda e: (e.role, e.name or e.automation_id)
    old = {key(e): e for e in before.elements}
    new = {key(e): e for e in after.elements}
    out = []
    for k, e in new.items():
        if k not in old:
            out.append(f'apareció {e.role} "{e.name or e.automation_id}"')
        else:
            o = old[k]
            if o.value != e.value and not e.secret:
                out.append(f'{e.role} "{e.name or e.automation_id}": valor "{o.value}" -> "{e.value}"')
            if o.checked != e.checked:
                out.append(f'{e.role} "{e.name or e.automation_id}": {"marcado" if e.checked else "desmarcado"}')
            if o.enabled != e.enabled:
                out.append(f'{e.role} "{e.name or e.automation_id}": {"habilitado" if e.enabled else "deshabilitado"}')
    for k, e in old.items():
        if k not in new:
            out.append(f'desapareció {e.role} "{e.name or e.automation_id}"')
    return "; ".join(out[:12]) + ("…" if len(out) > 12 else "") if out else "sin cambios visibles"
