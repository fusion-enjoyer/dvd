"""Pausing a build: the encoders and muxers it started (FFmpeg, HCEnc, spumux, dvdauthor)
are suspended and later resumed. The frames they read come through pipes from this
process, so its own work waits with them.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys


def children(pid: int | None = None) -> list[int]:
    """Every process started by `pid` (this one by default), and theirs, and so on."""
    pid = os.getpid() if pid is None else pid
    parents = _parents()
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        for child, parent in parents.items():
            if parent == p and child not in out and child != pid:
                out.append(child)
                todo.append(child)
    return out


def _parents() -> dict[int, int]:
    """Process id -> parent id for every process."""
    if sys.platform == "win32":
        return _parents_windows()
    out = {}
    for line in subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True,
                               check=False).stdout.splitlines():  # fmt: skip
        parts = line.split()
        if len(parts) == 2:
            out[int(parts[0])] = int(parts[1])
    return out


def _parents_windows() -> dict[int, int]:
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]  # fmt: skip

    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    out: dict[int, int] = {}
    entry = Entry()
    entry.dwSize = ctypes.sizeof(Entry)
    try:
        ok = kernel.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return out


def _windows_call(pid: int, name: str) -> bool:
    import ctypes

    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not handle:
        return False
    try:
        return getattr(ctypes.windll.ntdll, name)(handle) == 0
    finally:
        kernel.CloseHandle(handle)


def suspend(pids: list[int]) -> list[int]:
    """Suspend these processes; the ones that were suspended."""
    done = []
    for pid in pids:
        if sys.platform == "win32":
            if _windows_call(pid, "NtSuspendProcess"):
                done.append(pid)
        else:
            try:
                os.kill(pid, signal.SIGSTOP)
                done.append(pid)
            except OSError:
                pass
    return done


def resume(pids: list[int]) -> None:
    for pid in pids:
        if sys.platform == "win32":
            _windows_call(pid, "NtResumeProcess")
        else:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGCONT)


class Pause:
    """Pause and resume everything this process started."""

    def __init__(self) -> None:
        self.paused: list[int] = []

    @property
    def active(self) -> bool:
        return bool(self.paused)

    def pause(self) -> None:
        if not self.paused:
            self.paused = suspend(children())

    def resume(self) -> None:
        resume(self.paused)
        self.paused = []
