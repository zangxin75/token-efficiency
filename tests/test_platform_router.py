"""platform_router 测试：平台模式路由 + 透明计费。"""

import pytest

from tokeneff import config as cfg_module
from tokeneff.proxy import platform_router


@pytest.fixture
def platform_mode(monkeypatch, tmp_path):
    """切到 platform 模式 + 存测试 key。"""
    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    cfg.region = "cn"
    cfg_module.save(cfg)
    cfg_module.set_platform_key("sk-test-platform-xyz")
    yield cfg
    # 恢复 byok
    cfg.mode = "byok"
    cfg_module.save(cfg)


def test_route_cn_gateway(platform_mode):
    """cn 区域 → tokeneff.com。"""
    url, headers = platform_router.route("glm-4-flash", b'{"model":"glm-4-flash"}', {})
    assert url == "https://tokeneff.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test-platform-xyz"


def test_route_global_gateway(monkeypatch):
    """global 区域 → global.tokeneff.com。"""
    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    cfg.region = "global"
    cfg_module.save(cfg)
    cfg_module.load(force=True)  # 清内存缓存，让 route 读到新 region
    cfg_module.set_platform_key("sk-test-global")
    url, _ = platform_router.route("gpt-4o", b"{}", {})
    assert url == "https://global.tokeneff.com/v1/chat/completions"
    # 恢复
    cfg.region = "cn"; cfg.mode = "byok"; cfg_module.save(cfg)
    cfg_module.load(force=True)


def test_route_requires_platform_key(monkeypatch):
    """未配平台 key → RuntimeError。"""
    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    cfg_module.save(cfg)
    # 清空 platform key（用一个不存在的 account 模拟）
    monkeypatch.setattr(cfg_module, "get_platform_key", lambda: None)
    with pytest.raises(RuntimeError, match="平台模式未配置 key"):
        platform_router.route("glm-4-flash", b"{}", {})


def test_get_format_openai_for_glm(platform_mode):
    """glm → openai 格式。"""
    assert platform_router.get_format("glm-4-flash") == "openai"


def test_get_format_anthropic_for_claude(platform_mode):
    """claude → anthropic 格式。"""
    assert platform_router.get_format("claude-sonnet-4-6") == "anthropic"
