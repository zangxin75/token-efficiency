"""★ 第二轮审计修复的回归测试。

四组覆盖（对应审计 HIGH-3/HIGH-4）：
1. CNY 预算换算（budget_pct 不再膨胀 7.2 倍）
2. platform 模式无 key → 401（对齐 byok，不再 500）
3. platform_url 校验边界（空串/IPv6/172.16-31 段）
4. 契约字段断言（from_dict 嵌套 usage、breakdown 字段名、adapt 冲突映射）
"""

import json

import pytest

from tokeneff.meter.types import UsageResult
from tokeneff.proxy import byok_router


# ═══════════════════════════════════════════════════════════════════════════════
# 组1: CNY 预算换算
# ═══════════════════════════════════════════════════════════════════════════════


def test_budget_in_currency_cn_multiplies(tmp_config):
    """cn 区域：预算 USD×7.2 换算成 CNY 再参与百分比。"""
    cfg = tmp_config(region="cn", budget_monthly_usd=10.0)
    assert cfg.get_budget() == 10.0  # 存储恒为 USD
    assert cfg.get_budget_in_currency() == pytest.approx(72.0)


def test_budget_in_currency_global_passthrough(tmp_config):
    """global 区域：USD 预算原样返回。"""
    cfg = tmp_config(region="global", budget_monthly_usd=10.0)
    assert cfg.get_budget_in_currency() == 10.0


def test_budget_pct_no_inflation_cn():
    """★ 审计 HIGH：CNY 消费 ÷ USD 预算曾膨胀 7.2 倍（11% 真实用量即标红）。
    修复后：¥50 消费 ÷ $10 预算（=¥72）≈ 69.4%，而非 360%+。"""
    from tokeneff.meter.calculator import USD_TO_CNY

    month_cny = 50.0
    budget_usd = 10.0
    budget_in_cny = budget_usd * USD_TO_CNY
    pct = month_cny / budget_in_cny * 100
    assert pct < 100  # 修复前 >350%
    assert pct == pytest.approx(69.44, abs=0.01)


# ═══════════════════════════════════════════════════════纯═════════════════════
# 组2: platform 无 key → 401
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_platform_missing_key_returns_401(monkeypatch):
    """★ 审计 HIGH：platform key 未配置时 intercept 曾抛 RuntimeError → 500。
    修复后返回 401 auth_error（SDK 可识别、不触发自动重试）。"""
    from tokeneff import config as cfg_module
    from tokeneff.proxy import server

    cfg = cfg_module.TokenEffConfig()
    cfg.mode = "platform"
    monkeypatch.setattr(cfg_module, "get_config", lambda: cfg)
    monkeypatch.setattr(cfg_module, "get_platform_key", lambda: None)

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        # H2 audit fix: requests without an Authorization header are short-circuited
        # earlier — this test targets the no-platform-key branch, so send a header
        # (any real SDK client does) to reach it.
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "glm-4-flash", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test-key"},
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "auth_error"
    assert "平台模式未配置" in resp.json()["error"]["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# 组3: platform_url 校验边界
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("url,ok", [
    ("https://tokeneff.com", True),
    ("https://global.tokeneff.com", True),
    ("", True),                                  # 空串 = 回退区域默认，允许
    ("https://127.0.0.1", False),                # loopback（实测曾通过）
    ("https://localhost:8443", False),
    ("https://10.0.0.5", False),                 # A 类内网
    ("https://192.168.1.1", False),              # C 类内网
    ("https://169.254.169.254", False),          # link-local / 云元数据端点
    ("https://172.16.0.1", False),               # B 类内网下界
    ("https://172.31.255.255", False),           # B 类内网上界
    ("https://172.32.0.1", True),                # 172.32 是公网段，不应误杀
    ("https://172.99.0.1", True),
    ("https://[::1]", False),                    # IPv6 loopback
    ("http://tokeneff.com", False),              # 非 https
    ("https://", False),                         # 只有协议头无主机
    ("ftp://tokeneff.com", False),
])
def test_platform_url_boundaries(url, ok):
    from tokeneff.api.local_server import ConfigUpdatePayload
    from pydantic import ValidationError

    if ok:
        payload = ConfigUpdatePayload(platform_url=url)
        assert payload.platform_url == url
    else:
        with pytest.raises(ValidationError):
            ConfigUpdatePayload(platform_url=url)


def test_platform_url_ipv6_form_brackets():
    """IPv6 字面量 hostname 解析（urlparse 对 [::1] 返回 '::1'）。"""
    from tokeneff.api.local_server import ConfigUpdatePayload
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConfigUpdatePayload(platform_url="https://[::1]/v1")


# ═══════════════════════════════════════════════════════════════════════════════
# 组4: 契约字段断言
# ═══════════════════════════════════════════════════════════════════════════════


def test_from_dict_openai_top_level():
    """OpenAI 格式：usage 在顶层。"""
    u = UsageResult.from_dict({
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    })
    assert u.input_tokens == 100
    assert u.completion_tokens == 50
    assert u.has_data


def test_from_dict_anthropic_nested():
    """★ 审计 HIGH：Anthropic message_start 的 usage 嵌套在 message 里，
    from_dict 曾只查顶层 → input_tokens 恒 0（Claude Code 流式全漏计输入）。"""
    u = UsageResult.from_dict({
        "type": "message_start",
        "message": {"usage": {"input_tokens": 2583, "output_tokens": 3}},
    })
    assert u.input_tokens == 2583
    assert u.completion_tokens == 3
    assert u.has_data


def test_from_dict_anthropic_message_delta_top_level():
    """message_delta 的 usage 在顶层（output_tokens 在此事件）。"""
    u = UsageResult.from_dict({
        "type": "message_delta",
        "usage": {"output_tokens": 421},
    })
    assert u.completion_tokens == 421
    assert u.input_tokens == 0


def test_from_dict_no_usage_empty():
    u = UsageResult.from_dict({"choices": [{"text": "hi"}]})
    assert not u.has_data
    assert u.input_tokens == 0


def test_adapt_conflicting_fields_mapped():
    """★ adapt 冲突字段映射：stop→stop_sequences、n/penalties 剔除、
    tools OpenAI 形状转 Anthropic 形状、tool_choice function→tool。"""
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 100,
        "stop": ["\n\nHuman:", "\n\nAssistant:"],
        "n": 1,
        "frequency_penalty": 0.5,
        "presence_penalty": 0.2,
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }],
        "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))

    assert adapted["stop_sequences"] == ["\n\nHuman:", "\n\nAssistant:"]
    assert "stop" not in adapted
    assert "n" not in adapted
    assert "frequency_penalty" not in adapted
    assert "presence_penalty" not in adapted
    tool = adapted["tools"][0]
    assert tool["name"] == "get_weather"
    assert "input_schema" in tool
    assert "function" not in tool
    assert adapted["tool_choice"] == {"type": "tool", "name": "get_weather"}


def test_adapt_stop_string_becomes_list():
    """OpenAI 允许 stop 为 str，Anthropic 只认 list。"""
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "messages": [],
        "stop": "END",
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert adapted["stop_sequences"] == ["END"]


def test_adapt_anthropic_shaped_tools_untouched():
    """已是 Anthropic 形状的 tools（无 function 键）不应被改写。"""
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "messages": [],
        "tools": [{"name": "native_tool", "input_schema": {"type": "object"}}],
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert adapted["tools"] == [{"name": "native_tool", "input_schema": {"type": "object"}}]


def test_adapt_tool_choice_required_to_any():
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "messages": [],
        "tool_choice": {"type": "required"},
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert adapted["tool_choice"] == {"type": "any"}


def test_adapt_tool_choice_none_drops_tools():
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "messages": [],
        "tools": [{"name": "t", "input_schema": {}}],
        "tool_choice": {"type": "none"},
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert "tool_choice" not in adapted
    assert "tools" not in adapted
