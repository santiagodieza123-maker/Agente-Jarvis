"""Backend de Windows: UI Automation (`uiautomation`) + SendInput. Todas las operaciones de UIA corren en UN hilo con COM
inicializado (los controles no se pueden compartir entre hilos). Las ventanas se enumeran con la API Win32 (rápido y sin COM)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from concurrent.futures import ThreadPoolExecutor

import actuators.input_win32 as inp           # fija DPI Per-Monitor V2 antes de crear nada: UIA, mss y SendInput comparten píxeles físicos
from perception import som
from perception.backend import GuiBackend, GuiError
from perception.model import INTERACTIVE, READABLE, Element, Snapshot, WindowInfo

user32, kernel32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
dwm = ctypes.WinDLL("dwmapi")
OBSERVE_BUDGET = 8.0          # s
MOVE_TOLERANCE = 8            # px: si el elemento se movió más que esto desde la observación, no se actúa


def _process_name(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wt.DWORD(520)
        return buf.value.rsplit("\\", 1)[-1] if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        kernel32.CloseHandle(h)


def _window_info(hwnd: int, fg: int) -> WindowInfo | None:
    if not user32.IsWindowVisible(hwnd):
        return None
    cloaked = wt.DWORD(0)
    if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
        return None                                                    # ventanas de UWP en segundo plano
    if user32.GetWindowLongW(hwnd, -20) & 0x80:                        # WS_EX_TOOLWINDOW
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return None
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    if r.right - r.left <= 1 or r.bottom - r.top <= 1:
        return None
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return WindowInfo(hwnd, buf.value, _process_name(pid.value), pid.value, (r.left, r.top, r.right, r.bottom), hwnd == fg)


class UIABackend(GuiBackend):
    def __init__(self):
        import uiautomation as auto
        self.auto = auto
        self._ex = ThreadPoolExecutor(1, thread_name_prefix="uia", initializer=self._init_thread)
        self._seq = 0
        self._snaps: dict[int, dict[int, tuple[object, tuple[int, int, int, int]]]] = {}

    def _init_thread(self) -> None:
        init = getattr(self.auto, "InitializeUIAutomationInCurrentThread", None)
        if init:
            init()

    def run(self, fn, *args):
        return self._ex.submit(fn, *args).result(timeout=60)

    # ---------- ventanas ----------
    def windows(self) -> list[WindowInfo]:
        fg = user32.GetForegroundWindow()
        out: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def cb(hwnd, _):
            w = _window_info(hwnd, fg)
            if w:
                out.append(w)
            return True
        user32.EnumWindows(cb, 0)
        return out

    def foreground(self) -> WindowInfo | None:
        fg = user32.GetForegroundWindow()
        return _window_info(fg, fg) if fg else None

    def focus_window(self, handle: int) -> None:
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)                               # SW_RESTORE
        user32.keybd_event(0x12, 0, 0, 0)                              # un toque de Alt desbloquea el cambio de primer plano
        user32.keybd_event(0x12, 0, 2, 0)
        if not user32.SetForegroundWindow(handle):
            raise GuiError("Windows no permitió traer la ventana al primer plano")
        time.sleep(0.15)

    # ---------- observación ----------
    @staticmethod
    def _role(c) -> str:
        return c.ControlTypeName.replace("Control", "").lower()

    def _element(self, c, eid: int, depth: int) -> Element | None:
        role = self._role(c)
        if role not in INTERACTIVE and role not in READABLE:
            return None
        if c.IsOffscreen:
            return None
        r = c.BoundingRectangle
        rect = (r.left, r.top, r.right, r.bottom)
        if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
            return None
        name = (c.Name or "").strip()
        if role in READABLE and not name and role != "document":
            return None
        secret = bool(getattr(c, "IsPassword", False))
        value = checked = None
        if not secret:
            if role in ("edit", "combobox", "document", "spinner", "slider"):
                try:
                    vp = c.GetValuePattern()
                    value = vp.Value if vp else None
                    if value is None and role == "document":
                        tp = c.GetTextPattern()
                        value = tp.DocumentRange.GetText(500) if tp else None
                except Exception:
                    value = None
            if role in ("checkbox", "radiobutton", "treeitem", "listitem", "menuitem"):
                try:
                    tg = c.GetTogglePattern()
                    checked = (tg.ToggleState == 1) if tg else None
                    if checked is None and role in ("radiobutton", "listitem"):
                        sp = c.GetSelectionItemPattern()
                        checked = bool(sp.IsSelected) if sp else None
                except Exception:
                    checked = None
        return Element(eid, name, role, rect, bool(c.IsEnabled), (value[:300] if isinstance(value, str) else value), checked,
                       c.AutomationId or "", depth, secret)

    def observe(self, handle: int | None, max_elements: int) -> Snapshot:
        hwnd = handle or user32.GetForegroundWindow()
        info = _window_info(hwnd, user32.GetForegroundWindow())
        if info is None:
            raise GuiError("la ventana no existe o no está visible")
        try:
            top = self.auto.ControlFromHandle(hwnd)
        except Exception as e:
            raise GuiError(f"UI Automation no pudo abrir la ventana: {e}") from None
        if top is None:
            raise GuiError("UI Automation no pudo abrir la ventana")
        els: list[Element] = []
        refs: dict[int, tuple[object, tuple[int, int, int, int]]] = {}
        t0, truncated = time.time(), False
        for c, depth in self.auto.WalkControl(top, includeTop=False, maxDepth=12):
            if len(els) >= max_elements or time.time() - t0 > OBSERVE_BUDGET:
                truncated = True
                break
            try:
                e = self._element(c, len(els) + 1, depth)
            except Exception:
                continue                                               # un control que desaparece durante el recorrido
            if e is not None:
                els.append(e)
                refs[e.id] = (c, e.rect)
        self._seq += 1
        self._snaps[self._seq] = refs
        for old in sorted(self._snaps)[:-6]:
            del self._snaps[old]
        return Snapshot(self._seq, info, els, truncated)

    def _control(self, seq: int, element_id: int):
        refs = self._snaps.get(seq)
        if refs is None or element_id not in refs:
            raise GuiError("observación obsoleta: vuelve a observar")
        c, rect0 = refs[element_id]
        try:
            if not c.Exists(0, 0):
                raise GuiError("el elemento ya no existe")
            r = c.BoundingRectangle
        except GuiError:
            raise
        except Exception:
            raise GuiError("el elemento ya no es accesible") from None
        if max(abs(r.left - rect0[0]), abs(r.top - rect0[1])) > MOVE_TOLERANCE:
            raise GuiError("el elemento se ha movido desde la observación: vuelve a observar")
        return c, (r.left, r.top, r.right, r.bottom)

    # ---------- acciones ----------
    def activate(self, seq: int, element_id: int) -> str:
        c, rect = self._control(seq, element_id)
        for getter, act, name in (("GetInvokePattern", "Invoke", "invocar"), ("GetTogglePattern", "Toggle", "alternar"),
                                  ("GetSelectionItemPattern", "Select", "seleccionar"), ("GetExpandCollapsePattern", "Expand", "expandir")):
            try:
                pat = getattr(c, getter)()
                if pat:
                    getattr(pat, act)()
                    return name
            except Exception:
                continue
        top = c.GetTopLevelControl()
        if top is not None and top.NativeWindowHandle:
            self.focus_window(top.NativeWindowHandle)
        inp.click((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        return "clic"

    def set_value(self, seq: int, element_id: int, text: str) -> str:
        c, _ = self._control(seq, element_id)
        try:
            vp = c.GetValuePattern()
            if vp and not vp.IsReadOnly:
                vp.SetValue(text)
                return "valor"
        except Exception:
            pass
        c.SetFocus()
        inp.press("ctrl+a")
        inp.type_text(text)
        return "teclado"

    def read_value(self, seq: int, element_id: int) -> str | None:
        c, _ = self._control(seq, element_id)
        try:
            vp = c.GetValuePattern()
            return vp.Value if vp else None
        except Exception:
            return None

    # ---------- entrada y pantalla ----------
    def screenshot(self, rect):
        return som.capture(rect)[0]

    def press(self, combo: str) -> None:
        inp.press(combo)

    def type_text(self, text: str) -> None:
        inp.type_text(text)

    def click_xy(self, x: int, y: int) -> None:
        inp.click(x, y)
