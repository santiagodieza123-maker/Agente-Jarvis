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
