"""platform_router 测试：平台模式路由 + 透明计费。

★ 测试隔离修复（2026-08-15 事故复盘）：此前 fixture 直接调 cfg_module.save()
写真实 ~/.tokeneff/config.toml、set_platform_key() 写真实系统 keyring ——
每次跑测试就把用户的 mode/region/网关 key 悡盖成测试值且 teardown 无法恢复
原值。曾导致：真 key 被假值覆盖（网关 401）、mode 被改回 byok（请求绕过
网关直连智谱 → tools 400）。现在 fixture 把 CONFIG_PATH 重定向到 tmp_path，
keyring 读写全部 monkeypatch 成内存 dict，测试值不再触达真实存储。
"""

import pytest

from tokeneff import config as cfg_module
from tokeneff.proxy import platform_router


@pytest.fixture
def platform_mode(monkeypatch, tmp_path):
    """切到 platform 模式 + 存测试 key（完全隔离：config 落 tmp，key 在内存）。"""
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_module, "CONFIG_PATH", tmp_path / "config.toml")
    _fake = {"key": "sk-test-platform-xyz"}
    monkeypatch.setattr(cfg_module, "set_platform_key",
                        lambda v: _fake.update(key=v) or True)
    monkeypatch.setattr(cfg_module, "get_platform_key",
                        lambda: _fake["key"])
    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    cfg.region = "cn"
    cfg_module.save(cfg)
    cfg_module.load(force=True)
    yield cfg
    cfg_module._config = None  # 清内存缓存，不让测试配置泄漏到后续进程


def test_route_cn_gateway(platform_mode):
    """cn 区域 → tokeneff.com。"""
    url, headers = platform_router.route("glm-4-flash", b'{"model":"glm-4-flash"}', {})
    assert url == "https://tokeneff.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test-platform-xyz"


def test_route_global_gateway(monkeypatch, tmp_path):
    """global 区域 → global.tokeneff.com。"""
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_module, "CONFIG_PATH", tmp_path / "config.toml")
    _fake = {"key": "sk-test-global"}
    monkeypatch.setattr(cfg_module, "set_platform_key",
                        lambda v: _fake.update(key=v) or True)
    monkeypatch.setattr(cfg_module, "get_platform_key",
                        lambda: _fake["key"])
    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    cfg.region = "global"
    cfg_module.save(cfg)
    cfg_module.load(force=True)
    url, _ = platform_router.route("gpt-4o", b"{}", {})
    assert url == "https://global.tokeneff.com/v1/chat/completions"
    cfg_module._config = None


def test_route_requires_platform_key(monkeypatch, tmp_path):
    """未配平台 key → RuntimeError。"""
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    cfg_module.save(cfg)
    cfg_module.load(force=True)
    monkeypatch.setattr(cfg_module, "get_platform_key", lambda: None)
    with pytest.raises(RuntimeError, match="平台模式未配置 key"):
        platform_router.route("glm-4-flash", b"{}", {})
    cfg_module._config = None


def test_get_format_openai_for_glm(platform_mode):
    """glm → openai 格式。"""
    assert platform_router.get_format("glm-4-flash") == "openai"


def test_get_format_anthropic_for_claude(platform_mode):
    """claude → anthropic 格式。"""
    assert platform_router.get_format("claude-sonnet-4-6") == "anthropic"
