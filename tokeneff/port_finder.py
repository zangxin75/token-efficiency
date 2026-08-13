"""Port auto-discovery utility (★ M1 revision).

On sidecar startup, probes the target port; if occupied, increments and retries,
returning the actually available port (written to config + reported back to the frontend).
"""

from __future__ import annotations

import socket


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Probe whether a port is available (bindable means free)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
