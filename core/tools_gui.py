"""Herramientas gui.*: ver y manejar aplicaciones de escritorio por UI Automation, con elementos numerados.
Reglas de seguridad (ver README): el HUD de Jarvis nunca es visible ni accionable para el agente (si no, podría pulsar él
mismo «Permitir»); los campos de contraseña no se leen ni se rellenan; el contenido de las ventanas es no confiable (tras
observarlas, cualquier acción posterior pide confirmación); las teclas se limitan a una lista segura."""
from __future__ import annotations

import asyncio
import re
from typing import Callable

from core.orchestrator import Tool
from core.policy import ActionClass
from perception import som
from perception.backend import GuiBackend, GuiError
from perception.model import Element, Snapshot, WindowInfo, diff_summary

PROTECTED_PROCESSES = {"jarvis-hud.exe", "jarvis-hud"}
MAX_ELEMENTS = 120
MAX_TYPE = 2000
# Teclas y combinaciones admitidas en gui.press (minúsculas). Fuera de la lista: no se envían.
SAFE_KEYS = ({"enter", "tab", "esc", "escape", "backspace", "delete", "home", "end", "pageup", "pagedown", "up", "down", "left", "right", "space"}
             | {f"f{i}" for i in range(1, 13) if i != 4}
             | {"shift+tab"} | {f"ctrl+{c}" for c in "acvxzysfpnotw"} | {"ctrl+shift+z", "ctrl+home", "ctrl+end", "alt+left", "alt+right"})


class GuiResult(str):
    """Texto para el modelo con metadatos: `ok` (postcondición cumplida), `image` (captura anotada para la siguiente llamada)
    y `recipe_args` (argumentos estables —por nombre, no por número— con los que esta llamada puede repetirse en una receta)."""
    ok: bool = True
    image: bytes | None = None
    recipe_args: dict | None = None

    def __new__(cls, text: str, ok: bool = True, image: bytes | None = None, recipe_args: dict | None = None):
        o = super().__new__(cls, text)
        o.ok, o.image, o.recipe_args = ok, image, recipe_args
        return o


def is_protected(w: WindowInfo) -> bool:
    t = (w.title or "").strip()
    return (w.process or "").lower() in PROTECTED_PROCESSES or t == "Jarvis" or "J.A.R.V.I.S" in t


class GuiTools:
    def __init__(self, backend: GuiBackend, on_frame: Callable[[dict], None] | None = None, settle: float = 0.4):
        self.backend, self.on_frame, self.settle = backend, on_frame, settle
        self._snap: Snapshot | None = None

    # ---------- utilidades ----------
    async def _bk(self, fn, *args):
        return await asyncio.to_thread(self.backend.run, fn, *args)

    async def _visible_windows(self) -> list[WindowInfo]:
        return [w for w in await self._bk(self.backend.windows) if not is_protected(w)]

    async def _pick(self, window: str) -> WindowInfo:
        wins = await self._visible_windows()
        if window:
            q = window.lower()
            cand = [w for w in wins if q in w.title.lower() or q in w.process.lower() or str(w.handle) == window]
            if not cand:
                raise GuiError(f"no hay ninguna ventana que contenga '{window}'; usa gui.windows")
            return next((w for w in cand if w.foreground), cand[0])
        fg = await self._bk(self.backend.foreground)
        if fg is None or is_protected(fg):
            raise GuiError("la ventana activa es Jarvis o no hay ninguna; indica la ventana (gui.windows) o ponla en primer plano con gui.focus")
        return fg

    async def _frame(self, snap: Snapshot, highlight: int | None = None, action: str = "", want_llm_image: bool = False) -> bytes | None:
        """Captura la ventana, avisa al HUD y, si se pide, devuelve la imagen anotada para el modelo."""
        if self.on_frame is None and not want_llm_image:
            return None
        try:
            r = snap.window.rect
            valid = r[2] > r[0] and r[3] > r[1]
            png = await self._bk(self.backend.screenshot, r if valid else None)
            origin = (r[0], r[1]) if valid else (0, 0)
        except Exception:
            return None                                              # sin pantalla (p. ej. servidor sin escritorio): el texto basta
        if self.on_frame is not None:
            try:
                self.on_frame(await asyncio.to_thread(som.hud_frame, png, snap, origin, highlight, action))
            except Exception:
                pass
        return await asyncio.to_thread(som.annotate, png, snap, origin, highlight) if want_llm_image else None

    async def _observe(self, window: WindowInfo, ) -> Snapshot:
        snap = await self._bk(self.backend.observe, window.handle, MAX_ELEMENTS)
        if is_protected(snap.window):
            raise GuiError("esa ventana no es accesible para el agente")
        self._snap = snap
        return snap

    def _element(self, element_id):
        if self._snap is None:
            raise GuiError("no hay observación previa: usa gui.observe")
        if isinstance(element_id, bool) or not isinstance(element_id, (int, float)) or int(element_id) != element_id:
            raise GuiError("el número de elemento debe ser un entero")
        el = self._snap.get(int(element_id))
        if el is None:
            raise GuiError(f"el elemento {element_id} no existe en la última observación (#{self._snap.seq}); vuelve a observar")
        return el

    def _target(self, id, name, role, nth) -> tuple[Element, dict]:
        """Elemento por número (de la última observación) o por nombre/rol (estable entre ejecuciones: lo que usan las recetas).
        Devuelve también los argumentos estables para registrar la llamada."""
        if self._snap is None:
            raise GuiError("no hay observación previa: usa gui.observe")
        if name:
            q = str(name).strip().lower()
            cand = [e for e in self._snap.elements if (e.name or e.automation_id).strip().lower() == q and (not role or e.role == str(role).lower())]
            if not cand:
                raise GuiError(f'no hay ningún elemento "{name}"' + (f" de tipo {role}" if role else "") + " en la última observación")
            if nth is None and len(cand) > 1:
                raise GuiError(f'"{name}" es ambiguo ({len(cand)} coincidencias: ' + ", ".join(f"[{e.id}] {e.role}" for e in cand[:6]) + "); indica el número o nth")
            idx = 0 if nth is None else int(nth)
            if isinstance(nth, bool) or not 0 <= idx < len(cand):
                raise GuiError(f"nth fuera de rango (0..{len(cand) - 1})")
            el = cand[idx]
        else:
            el = self._element(id)
        key = el.name or el.automation_id
        same = [e for e in self._snap.elements if (e.name or e.automation_id) == key and e.role == el.role]
        stable = {"name": key, "role": el.role} if key else {}
        if key and len(same) > 1:
            stable["nth"] = same.index(el)
        return el, stable

    async def _after(self, action: str, el_id: int | None, before: Snapshot, ok: bool = True) -> GuiResult:
        await asyncio.sleep(self.settle)
        win = before.window
        try:
            after = await self._observe(win)
        except GuiError as e:
            return GuiResult(f"{action}. No se pudo volver a observar la ventana: {e}", ok)
        await self._frame(after, None, action)
        return GuiResult(f"{action}. Cambios: {diff_summary(before, after)}.\n{after.describe()}", ok)

    # ---------- herramientas ----------
    async def windows(self) -> str:
        wins = await self._visible_windows()
        if not wins:
            return "No hay ventanas visibles."
        return "\n".join(f'{"*" if w.foreground else " "} "{w.title[:80]}" ({w.process}) id={w.handle}' for w in wins[:40])

    async def observe(self, window: str = "", image: bool = False) -> GuiResult:
        w = await self._pick(window)
        snap = await self._observe(w)
        img = await self._frame(snap, None, "observar", want_llm_image=bool(image))
        text = snap.describe()
        if image and img is None:
            text += "\n(no se pudo capturar la pantalla; se usa solo la descripción)"
        return GuiResult(text, True, img)

    async def focus(self, window: str) -> GuiResult:
        w = await self._pick(window)
        await self._bk(self.backend.focus_window, w.handle)
        snap = await self._observe(w)
        await self._frame(snap, None, f"enfocar {w.title}")
        return GuiResult(f'Ventana "{w.title}" en primer plano.\n{snap.describe()}')

    async def click(self, id: int | None = None, name: str = "", role: str = "", nth: int | None = None) -> GuiResult:
        el, stable = self._target(id, name, role, nth)
        if not el.enabled:
            return GuiResult(f"El elemento {el.id} está deshabilitado.", False)
        if el.secret:
            return GuiResult("Los campos de contraseña no son accesibles.", False)
        before = self._snap
        await self._frame(before, el.id, f'clic en {el.id} "{el.name}"')
        method = await self._bk(self.backend.activate, before.seq, el.id)
        res = await self._after(f'Clic en {el.id} ({el.role} "{el.name[:40]}") mediante {method}', el.id, before)
        res.recipe_args = stable or None
        return res

    async def type(self, id: int | None = None, text: str = "", name: str = "", role: str = "", nth: int | None = None, submit: bool = False) -> GuiResult:
        el, stable = self._target(id, name, role, nth)
        if el.secret:
            return GuiResult("Los campos de contraseña no son accesibles.", False)
        if el.role not in ("edit", "combobox", "document"):
            return GuiResult(f"El elemento {el.id} es un {el.role}, no un campo de texto.", False)
        if not isinstance(text, str) or len(text) > MAX_TYPE:
            return GuiResult(f"Texto inválido (máx. {MAX_TYPE} caracteres).", False)
        before = self._snap
        await self._frame(before, el.id, f'escribir en {el.id}')
        method = await self._bk(self.backend.set_value, before.seq, el.id, text)
        got = await self._bk(self.backend.read_value, before.seq, el.id)
        ok = got is None or got == text                                  # postcondición: el campo contiene lo escrito
        if submit:
            await self._bk(self.backend.press, "enter")
        res = await self._after(f'Escrito en {el.id} mediante {method}' + ("" if ok else f' (¡el campo contiene "{(got or "")[:60]}", no lo escrito!)'), el.id, before, ok)
        res.recipe_args = ({**stable, "text": text, **({"submit": True} if submit else {})}) if stable else None
        return res

    async def press(self, keys: str) -> GuiResult:
        combo = re.sub(r"\s+", "", str(keys).lower())
        if combo not in SAFE_KEYS:
            return GuiResult(f"Tecla no permitida: {keys!r}. Permitidas: {', '.join(sorted(SAFE_KEYS))}", False)
        if self._snap is None:
            return GuiResult("Observa primero una ventana (gui.observe).", False)
        before = self._snap
        fg = await self._bk(self.backend.foreground)
        if fg is None or is_protected(fg):
            return GuiResult("La ventana activa es Jarvis o no hay ninguna: no se envían teclas. Usa gui.focus.", False)
        if fg.handle != before.window.handle:
            return GuiResult(f'La ventana activa es "{fg.title}", no la observada ("{before.window.title}"). Usa gui.focus primero.', False)
        await self._bk(self.backend.press, combo)
        return await self._after(f"Tecla {combo}", None, before)

    async def click_xy(self, x: int, y: int) -> GuiResult:
        """Último recurso cuando UI Automation no expone el control. Coordenadas físicas del escritorio; solo dentro de la ventana observada."""
        if self._snap is None:
            return GuiResult("Observa primero una ventana (gui.observe).", False)
        l, t, r, b = self._snap.window.rect
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (x, y)) or not (l <= x < r and t <= y < b):
            return GuiResult(f"El punto ({x},{y}) está fuera de la ventana observada {self._snap.window.rect}.", False)
        for w in await self._bk(self.backend.windows):
            if is_protected(w) and w.rect[0] <= x < w.rect[2] and w.rect[1] <= y < w.rect[3]:
                return GuiResult("Ese punto está sobre la ventana de Jarvis: no se hace clic.", False)
        before = self._snap
        await self._bk(self.backend.click_xy, int(x), int(y))
        return await self._after(f"Clic en coordenadas ({int(x)},{int(y)})", None, before)

    def tools(self) -> list[Tool]:
        def p(required=(), **f):
            return {"type": "object", "properties": {k: {"type": t} for k, t in f.items()}, "required": [k for k in f if k in required]}
        R, W, D = ActionClass.READ, ActionClass.WRITE_REVERSIBLE, ActionClass.DESTRUCTIVE
        ver = lambda out: getattr(out, "ok", True)
        return [
            Tool("gui.windows", R, self.windows, "Lista las ventanas abiertas (la activa lleva *)", True),
            Tool("gui.observe", R, self.observe, "Observa una ventana (por parte del título; vacío = la activa) y numera sus elementos. image=true adjunta una captura con los números dibujados. Los números cambian en cada observación o acción: usa siempre los últimos", True,
                 parameters=p(window="string", image="boolean")),
            Tool("gui.focus", W, self.focus, "Trae una ventana al primer plano y la observa", True, parameters=p(("window",), window="string")),
            Tool("gui.click", W, self.click, "Pulsa un elemento: por su número (id, de la última observación) o por name (+role, nth si hay varios iguales). Devuelve la ventana tras la acción", True, verify=ver, parameters=p(id="integer", name="string", role="string", nth="integer")),
            Tool("gui.type", W, self.type, "Escribe texto en un campo (por id o por name/role); submit=true pulsa Enter después", True, verify=ver, parameters=p(("text",), text="string", id="integer", name="string", role="string", nth="integer", submit="boolean")),
            Tool("gui.press", W, self.press, "Pulsa una tecla o combinación segura (enter, tab, esc, flechas, ctrl+a/c/v/x/z/y/s/f, f1..f12…)", True, verify=ver, parameters=p(("keys",), keys="string")),
            Tool("gui.click_xy", D, self.click_xy, "ÚLTIMO RECURSO: clic en coordenadas de pantalla dentro de la ventana observada, solo si el elemento no aparece numerado", True, verify=ver, parameters=p(("x", "y"), x="integer", y="integer")),
        ]
