"""Port auto-discovery utility (★ M1 revision).

On sidecar startup, probes the target port; if occupied, increments and retries,
returning the actually available port (written to config + reported back to the frontend).
"""

from __future__ import annotations

import socket


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Probe whether a port is available (bindable means free).

    ★ No SO_REUSEADDR: on Windows it permits binding over a port another process
    is actively LISTENING on, making occupied ports probe as free — the subsequent
    uvicorn bind then fails (10048). On POSIX REUSEADDR only reclaims TIME_WAIT
    sockets, which is irrelevant for a one-shot probe.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
        return True
    except OSError:
        return False


def find_free_port(preferred: int, max_port: int = None, host: str = "127.0.0.1") -> int:
    """Probe incrementally starting from preferred, return the first available port.

    Args:
        preferred: desired port
        max_port: probe upper bound (default preferred + 30)
        host: bind address (default loopback, reduces AV false positives)

    Returns:
        the actually available port

    Raises:
        RuntimeError: still no available port when the upper bound is reached
    """
    if max_port is None:
        max_port = preferred + 30
    for port in range(preferred, max_port + 1):
        if is_port_free(port, host):
            return port
    raise RuntimeError(
        f"端口 {preferred}~{max_port} 全部被占用。"
        f"请关闭占用进程或手动指定其他端口。"
    )
