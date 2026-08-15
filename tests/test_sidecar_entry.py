"""sidecar 进程应同时拉起计量代理（proxy）。

★ 回归背景：桌面版 sidecar 入口只启动管理 API (7861)，proxy (7860) 无人拉起，
外部 Claude Code 连 7860 拿到 ConnectionRefused。修复后 sidecar 进程内
以线程方式启动 proxy，两者共享 collector 单例。
"""

import socket
import time

import pytest


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """隔离 DB，避免测试写用户真实电表数据。"""
    from tokeneff.meter import store as store_mod

    db = tmp_path / "t.db"
    monkeypatch.setattr(store_mod, "DB_PATH", db)
    import asyncio

    from tokeneff.meter.store import UsageStore

    s = UsageStore(db)
    asyncio.run(s.init())
    yield
    asyncio.run(s.close())


class TestStartProxyThread:
    def test_starts_proxy_on_configured_port(self, isolated_db):
        """start_proxy_thread 调用后，proxy 应在指定端口上监听。"""
        from tokeneff.api.local_server import start_proxy_thread

        port = _free_port()
        start_proxy_thread(port=port)

        deadline = time.time() + 10
        while time.time() < deadline:
            if _port_open(port):
                break
            time.sleep(0.2)
        assert _port_open(port), f"proxy 未在 {port} 上监听"

    def test_proxy_thread_failure_does_not_raise(self, isolated_db):
        """proxy 线程异常（如端口被占）不应向调用方抛异常拖死 sidecar。"""
        from tokeneff.api.local_server import start_proxy_thread

        occupied = _free_port()
        holder = socket.socket()
        holder.bind(("127.0.0.1", occupied))
        holder.listen(1)
        try:
            start_proxy_thread(port=occupied)  # 不应抛
            time.sleep(1.5)
        finally:
            holder.close()

    def test_proxy_health_reachable_after_start(self, isolated_db):
        """proxy 启动后 /health 应答 200（外部客户端依赖此端口存活）。"""
        import httpx

        from tokeneff.api.local_server import start_proxy_thread

        port = _free_port()
        start_proxy_thread(port=port)

        deadline = time.time() + 10
        ok = False
        while time.time() < deadline:
            try:
                resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1, trust_env=False)
                if resp.status_code == 200:
                    ok = True
                    break
            except Exception:
                time.sleep(0.2)
        assert ok, "proxy /health 不可达"


class TestDualStackListen:
    def test_proxy_reachable_via_ipv6_loopback(self, isolated_db):
        """Node.js (Claude Code) 解析 localhost 优先 IPv6 (::1)。

        proxy 若只绑 127.0.0.1，::1 连接被拒 → Claude Code 回退直连绕过
        电表（终端能用但计量不动）。双栈监听后两条路径都必须可达。
        """
        import httpx

        from tokeneff.api.local_server import start_proxy_thread

        port = _free_port()
        start_proxy_thread(port=port)

        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                resp = httpx.get(f"http://[::1]:{port}/health", timeout=1, trust_env=False)
                if resp.status_code == 200:
                    break
            except Exception:
                time.sleep(0.2)
        else:
            pytest.fail("proxy 在 IPv6 loopback (::1) 上不可达")

        resp4 = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5, trust_env=False)
        assert resp4.status_code == 200, "IPv4 路径不可用"
