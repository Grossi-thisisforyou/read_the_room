"""Tell systemd we are alive (sd_notify), with the standard library only.

The service file sets WatchdogSec: if the frame loop stops pinging for that
long (a plugin hung, the loop froze), systemd kills and restarts the show.
Outside systemd NOTIFY_SOCKET is unset and every call does nothing.
"""
from __future__ import annotations

import os
import socket


def notify(state: str) -> bool:
    """Send e.g. "READY=1" or "WATCHDOG=1". True if it was sent."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return False
    if path.startswith("@"):
        path = "\0" + path[1:]          # abstract socket namespace
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(path)
            s.sendall(state.encode())
        return True
    except OSError:
        return False
