"""Transporte por tubería con nombre (solo Windows). La tubería solo admite al usuario actual y a SYSTEM, y rechaza clientes remotos."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import time

from broker.protocol import MAX_FRAME, ProtocolError, frame, parse, unframe_length

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

PIPE_ACCESS_DUPLEX = 3
PIPE_TYPE_BYTE, PIPE_READMODE_BYTE, PIPE_WAIT, PIPE_REJECT_REMOTE_CLIENTS = 0, 0, 0, 8
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
INVALID = ctypes.c_void_p(-1).value
ERROR_PIPE_CONNECTED, ERROR_PIPE_BUSY = 535, 231
GENERIC_RW = 0xC0000000
OPEN_EXISTING = 3

k32.CreateNamedPipeW.restype = wt.HANDLE
k32.CreateFileW.restype = wt.HANDLE
k32.GetCurrentProcess.restype = wt.HANDLE                       # pseudo-handle -1: sin restype truncaría a 32 bits
adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.CloseHandle.argtypes = [wt.HANDLE]
for fn in (k32.ReadFile, k32.WriteFile):
    fn.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wt.BOOL)]


def is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def user_sid() -> str:
    """SID (texto) del usuario del proceso actual."""
    tok = wt.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 8, ctypes.byref(tok)):        # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        n = wt.DWORD()
        adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(n))                      # TokenUser
        buf = ctypes.create_string_buffer(n.value)
        if not adv.GetTokenInformation(tok, 1, buf, n, ctypes.byref(n)):
            raise ctypes.WinError(ctypes.get_last_error())
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        s = wt.LPWSTR()
        if not adv.ConvertSidToStringSidW(ctypes.c_void_p(psid), ctypes.byref(s)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return s.value
        finally:
            k32.LocalFree(s)
    finally:
        k32.CloseHandle(tok)


def default_pipe_name() -> str:
    return r"\\.\pipe\jarvis-broker-" + hashlib.sha256(user_sid().encode()).hexdigest()[:12]


def pipe_sddl(sid: str | None = None) -> str:
    """DACL: control total solo al usuario actual y a SYSTEM. Nadie más (ni Everyone ni Authenticated Users)."""
    return f"D:P(A;;GA;;;{sid or user_sid()})(A;;GA;;;SY)"


def _security_attributes(sddl: str):
    psd = ctypes.c_void_p()
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(psd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd.value, False)
    return sa, psd


def _read_exact(h, n: int) -> bytes:
    out = b""
    while len(out) < n:
        buf = ctypes.create_string_buffer(n - len(out))
        got = wt.DWORD()
        if not k32.ReadFile(h, buf, n - len(out), ctypes.byref(got), None) or got.value == 0:
            raise ProtocolError("conexión cerrada")
        out += buf.raw[:got.value]
    return out


def _write_all(h, data: bytes) -> None:
    sent = 0
    while sent < len(data):
        chunk = data[sent:]
        w = wt.DWORD()
        if not k32.WriteFile(h, chunk, len(chunk), ctypes.byref(w), None):
            raise ctypes.WinError(ctypes.get_last_error())
        sent += w.value


def read_message(h) -> bytes:
    return _read_exact(h, unframe_length(_read_exact(h, 4)))


def serve(core, name: str, ready=None) -> None:
    """Atiende conexiones de una en una hasta que el núcleo marque `stopping`. Cada conexión: una petición, una respuesta."""
    sa, psd = _security_attributes(pipe_sddl())
    first = FILE_FLAG_FIRST_PIPE_INSTANCE                                              # si otro proceso ya creó la tubería, falla (no se suplanta)
    try:
        while not core.stopping:
            h = k32.CreateNamedPipeW(name, PIPE_ACCESS_DUPLEX | first, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                     1, 65536, 65536, 0, ctypes.byref(sa))
            if h in (None, INVALID):
                raise ctypes.WinError(ctypes.get_last_error())
            first = 0
            if ready is not None:
                ready()
                ready = None
            try:
                if not k32.ConnectNamedPipe(h, None) and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
                    continue
                try:
                    resp = core.handle_raw(read_message(h))
                except ProtocolError as e:
                    resp = {"id": "?", "ok": False, "error": str(e)}
                except OSError:
                    continue                                                           # cliente cortado a media lectura: el broker sigue
                except Exception as e:                                                 # una petición mal formada nunca tumba el servicio
                    resp = {"id": "?", "ok": False, "error": f"error interno: {type(e).__name__}"}
                try:
                    _write_all(h, frame(resp))
                    k32.FlushFileBuffers(h)
                    k32.DisconnectNamedPipe(h)
                except OSError:
                    pass
            finally:
                k32.CloseHandle(h)
    finally:
        k32.LocalFree(psd)


def call(name: str, request: dict, timeout: float = 30.0) -> dict:
    """Cliente: abre la tubería, envía una petición firmada y devuelve la respuesta."""
    deadline = time.time() + timeout
    gap = time.time() + 1.0                                                            # entre dos conexiones la tubería se recrea: ese hueco no es "broker caído"
    while True:
        h = k32.CreateFileW(name, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None)
        if h not in (None, INVALID):
            break
        err = ctypes.get_last_error()
        if err == ERROR_PIPE_BUSY and time.time() < deadline:
            k32.WaitNamedPipeW(name, 500)
            continue
        if err == 2 and time.time() < min(gap, deadline):
            time.sleep(0.05)
            continue
        raise ConnectionError("el broker elevado no está en marcha" if err == 2 else f"no se pudo abrir la tubería del broker (error {err})")
    try:
        _write_all(h, frame(request))
        return parse(read_message(h))
    finally:
        k32.CloseHandle(h)


def confirm_dialog(op: str, text: str) -> bool:
    """Diálogo propio del broker (proceso elevado): un proceso de integridad Medium no puede enviarle entrada (UIPI)."""
    MB_YESNO, MB_ICONWARNING, MB_DEFBUTTON2, MB_SETFOREGROUND, MB_TOPMOST = 0x4, 0x30, 0x100, 0x10000, 0x40000
    msg = f"Jarvis solicita una operación con privilegios de administrador:\n\n{text}\n\n¿Permitirla?"
    return u32.MessageBoxW(None, msg, "Jarvis · confirmación del broker elevado", MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SETFOREGROUND | MB_TOPMOST) == 6


def acl_of(name: str) -> str:
    """SDDL de la tubería existente `name` (para comprobar que nadie más tiene acceso)."""
    h = k32.CreateFileW(name, 0x20000, 3, None, OPEN_EXISTING, 0, None)                  # READ_CONTROL
    if h in (None, INVALID):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        psd = ctypes.c_void_p()
        if adv.GetSecurityInfo(h, 6, 4, None, None, None, None, ctypes.byref(psd)):      # SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION
            raise ctypes.WinError(ctypes.get_last_error())
        s = wt.LPWSTR()
        if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(psd, 1, 4, ctypes.byref(s), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return s.value
        finally:
            k32.LocalFree(s); k32.LocalFree(psd)
    finally:
        k32.CloseHandle(h)
