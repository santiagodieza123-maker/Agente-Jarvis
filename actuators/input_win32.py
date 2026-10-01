"""Actuador de entrada Win32 (solo Windows). Integridad Medium; sin elevar."""
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
# Per-Monitor V2: debe ejecutarse antes de crear cualquier ventana/GUI.
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


INPUT_MOUSE = 0
MOVE, LDOWN, LUP, VIRTUALDESK, ABSOLUTE = 0x1, 0x2, 0x4, 0x4000, 0x8000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


def _send(inputs) -> None:
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    if user32.SendInput(n, arr, ctypes.sizeof(INPUT)) != n:
        raise ctypes.WinError(ctypes.get_last_error())
    # Un bloqueo por UIPI NO se detecta aquí: verificar la postcondición vía UIA o captura.


def click(x: int, y: int) -> None:
    """x, y en píxeles físicos del escritorio virtual (mismo sistema que mss.monitors[0])."""
    vx, vy = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw, vh = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    nx = round((x - vx) * 65535 / (vw - 1))
    ny = round((y - vy) * 65535 / (vh - 1))
    evs = []
    for f in (MOVE, LDOWN, LUP):  # una sola llamada: sin intercalado ni botón pegado
        i = INPUT(type=INPUT_MOUSE)
        i.mi = MOUSEINPUT(nx, ny, 0, ABSOLUTE | VIRTUALDESK | f, 0, 0)
        evs.append(i)
    _send(evs)


INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x0002


def hotkey(*vks: int) -> None:
    """Pulsa y suelta una combinación (códigos de tecla virtual), en una sola llamada a SendInput."""
    evs = []
    for flags, keys in ((0, vks), (KEYEVENTF_KEYUP, reversed(vks))):
        for vk in keys:
            i = INPUT(type=INPUT_KEYBOARD)
            i.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
            evs.append(i)
    _send(evs)


# ---------- teclas por nombre y texto Unicode ----------
KEYEVENTF_UNICODE = 0x0004
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "delete": 0x2E,
      "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "space": 0x20,
      **{f"f{i}": 0x6F + i for i in range(1, 13)}, **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"},
      **{str(d): 0x30 + d for d in range(10)}}


def press(combo: str) -> None:
    """«ctrl+shift+z», «enter», «f5»…: nombres en minúsculas separados por '+'."""
    try:
        vks = [VK[p] for p in combo.lower().split("+")]
    except KeyError as e:
        raise ValueError(f"tecla desconocida: {e.args[0]}") from None
    hotkey(*vks)


def type_text(text: str) -> None:
    """Escribe texto Unicode (cualquier carácter, también tildes y emoji) con SendInput, en una sola llamada por bloque."""
    units = []
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        units.append(int.from_bytes(data[i:i + 2], "little"))
    for start in range(0, len(units), 200):            # bloques: evita eventos enormes
        evs = []
        for u in units[start:start + 200]:
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                i = INPUT(type=INPUT_KEYBOARD)
                i.ki = KEYBDINPUT(0, u, flags, 0, 0)
                evs.append(i)
        _send(evs)
