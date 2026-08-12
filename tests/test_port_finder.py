"""port_finder 端口自适应测试（★ M1）。"""

import socket

import pytest

from tokeneff.port_finder import find_free_port, is_port_free


def _occupy(port: int) -> socket.socket:
    """占用一个端口，返回 socket（调用方负责 close）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def test_free_port_detected():
    assert is_port_free(39999) is True


def test_occupied_port_detected():
    s = _occupy(39998)
    try:
        assert is_port_free(39998) is False
    finally:
        s.close()


def test_find_free_port_skips_occupied():
    s1 = _occupy(39990)
    s2 = _occupy(39991)
    try:
        # 39990、39991 被占，应跳到 39992
        assert find_free_port(39990) == 39992
    finally:
        s1.close(); s2.close()


def test_find_free_port_returns_preferred_when_free():
    assert find_free_port(39980) == 39980


def test_find_free_port_raises_when_exhausted():
    socks = [_occupy(p) for p in range(39970, 39973)]
    try:
        with pytest.raises(RuntimeError, match="全部被占用"):
            find_free_port(39970, max_port=39972)
    finally:
        for s in socks:
            s.close()
