"""端口自适应工具（★ M1 修订）。

sidecar 启动时探测目标端口，被占用则递增重试，
返回实际可用端口（写入 config + 回传前端显示）。
"""

from __future__ import annotations

import socket


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """探测端口是否可用（能 bind 即空闲）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def find_free_port(preferred: int, max_port: int = None, host: str = "127.0.0.1") -> int:
    """从 preferred 起递增探测，返回第一个可用端口。

    Args:
        preferred: 期望端口
        max_port: 探测上限（默认 preferred + 30）
        host: 绑定地址（默认回环，降低杀软误报）

    Returns:
        实际可用端口

    Raises:
        RuntimeError: 探测到上限仍无可用端口
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
