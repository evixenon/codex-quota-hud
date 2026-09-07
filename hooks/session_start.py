"""Start one detached quota HUD process for the active Codex session."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


HUD_MUTEX_NAME = r"Local\CodexQuotaHud"
SYNCHRONIZE = 0x00100000
ERROR_FILE_NOT_FOUND = 2


def _hud_is_running() -> bool:
    """Return whether a HUD process owns the Windows single-instance mutex."""
    if os.name != "nt":
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, HUD_MUTEX_NAME)
    if not handle:
        # Avoid creating a duplicate if another desktop context owns the mutex
        # but prevents this process from opening its handle.
        return ctypes.get_last_error() not in (0, ERROR_FILE_NOT_FOUND)
    try:
        return True
    finally:
        kernel32.CloseHandle(handle)


def main() -> None:
    if os.name != "nt":
        return

    plugin_root = Path(os.environ["PLUGIN_ROOT"])
    hud_script = plugin_root / "hud" / "codex_hud.py"
    # The HUD mutex is authoritative. Its PID file may survive a crash, and
    # os.kill(pid, 0) is not a reliable existence probe on Windows.
    if _hud_is_running():
        return

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        [sys.executable, str(hud_script)],
        cwd=str(hud_script.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )


if __name__ == "__main__":
    main()
