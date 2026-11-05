"""Is a process still running? Tells a crashed scheduler from a live one.

A job marked 'running' belongs to the scheduler that claimed it. If that
scheduler is alive the job is not abandoned, even when a second scheduler
(for example a ladder and a final sharing one results folder) looks at the
queue. Only a job whose owner has died may be handed out again.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

_WORKER = re.compile(r"^scheduler-(\d+)$")


def worker_pid(worker: Optional[str]) -> Optional[int]:
    """The process id inside a worker name such as 'scheduler-4242'."""
    match = _WORKER.match(worker or "")
    return int(match.group(1)) if match else None


def pid_alive(pid: int) -> bool:
    """True if a process with this id is running right now."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)  # signal 0: only checks that the process exists
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, it just belongs to someone else
    return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query_limited = 0x1000
    still_active = 259
    access_denied = 5
    handle = kernel32.OpenProcess(query_limited, False, pid)
    if not handle:
        # Access denied means the process exists but is not ours.
        return ctypes.get_last_error() == access_denied
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
