"""Watchdog independiente (solo Windows). Lanza al agente en un Job Object y lo mata con Ctrl+Shift+F10."""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import threading

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
k32.CreateJobObjectW.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]

MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
VK_F10 = 0x79
WM_QUIT, WM_HOTKEY = 0x0012, 0x0312
KILL_ON_JOB_CLOSE = 0x2000


class BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]


class IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("RO", "WO", "OO", "RT", "WT", "OT")]


class EXTENDED(ctypes.Structure):
    _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _release_modifiers() -> None:
    """key-up de Ctrl/Alt/Shift/Win para no dejar teclas pegadas tras matar al agente."""
    KEYUP = 0x0002
    for vk in (0x11, 0x12, 0x10, 0x5B):
        u32.keybd_event(vk, 0, KEYUP, 0)


def main() -> int:
    job = k32.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.Basic.LimitFlags = KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))

    agent = subprocess.Popen([sys.executable, "-m", "core.main"])
    hproc = k32.OpenProcess(0x0100 | 0x0001, False, agent.pid)  # SET_QUOTA | TERMINATE
    if not k32.AssignProcessToJobObject(job, hproc):
        agent.kill()
        raise ctypes.WinError(ctypes.get_last_error())

    tid = k32.GetCurrentThreadId()
    threading.Thread(
        target=lambda: (agent.wait(), u32.PostThreadMessageW(tid, WM_QUIT, 0, 0)), daemon=True
    ).start()

    if not u32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F10):
        k32.TerminateJobObject(job, 1)
        raise ctypes.WinError(ctypes.get_last_error())

    msg = wt.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            k32.TerminateJobObject(job, 1)  # mata al agente y a todos sus hijos
            _release_modifiers()
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
