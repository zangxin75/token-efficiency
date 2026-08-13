"""byok_router 测试：route auth 分支 + adapt_request_body。"""

import json

import pytest

from tokeneff.proxy import byok_router


@pytest.fixture(autouse=True)
def _no_keyring_keys(monkeypatch):
    """route 测试隔离 keyring：强制 get_api_key 返回 None，
    使 router 走"请求头兜底"分支（用测试传入的 fake key）。

    ★ 修复：route 优先用 keyring key，若 keyring 里有真实/B0 测试残留 key，
    会覆盖测试传入的 fake key，导致断言不稳定。
    """
    monkeypatch.setattr(byok_router.cfg_module, "get_api_key", lambda provider: None)


# ── route auth 分支 ─────────────────────────────────────────────────────────


def test_route_openai_uses_bearer():
    """OpenAI 系用 Authorization: Bearer。"""
    url, headers = byok_router.route("gpt-4o", b'{"model":"gpt-4o"}',
                                      {"Authorization": "Bearer sk-fake"})
    assert "api.openai.com" in url
    assert headers["Authorization"] == "Bearer sk-fake"
    assert "x-api-key" not in headers


def test_route_anthropic_uses_x_api_key():
    """★ N-C3: Anthropic 用 x-api-key，无 Authorization。"""
    url, headers = byok_router.route("claude-sonnet-4-6", b'{"model":"claude-sonnet-4-6"}',
                                      {"Authorization": "Bearer sk-ant-fake"})
    assert "api.anthropic.com/v1/messages" in url
    assert headers["x-api-key"] == "sk-ant-fake"
    assert "Authorization" not in headers
    assert headers["anthropic-version"] == "2023-06-01"


def test_route_kimi_coding_anthropic_format():
    """Kimi Coding 走 api.kimi.com/coding/v1/messages（Anthropic 协议）。"""
    url, headers = byok_router.route("kimi-k2.6", b'{"model":"kimi-k2.6"}',
                                      {"Authorization": "Bearer sk-kimi-fake"})
    assert "api.kimi.com" in url
    assert "/coding/v1/messages" in url
    assert headers["x-api-key"] == "sk-kimi-fake"


def test_route_deepseek_openai_format():
    """DeepSeek 走 OpenAI 兼容端点。"""
    url, headers = byok_router.route("deepseek-v4-flash", b'{"model":"deepseek-v4-flash"}',
                                      {"Authorization": "Bearer sk-ds-fake"})
    assert "api.deepseek.com/v1/chat/completions" in url
    assert headers["Authorization"] == "Bearer sk-ds-fake"


def test_get_provider_format():
    """format 判定正确。"""
    assert byok_router.get_provider_format("claude-sonnet-4-6") == "anthropic"
    assert byok_router.get_provider_format("gpt-4o") == "openai"
    assert byok_router.get_provider_format("kimi-k2.6") == "anthropic"


# ── adapt_request_body ───────────────────────────────────────────────────────


def test_adapt_openai_to_anthropic_moves_system_to_top():
    """★ §4.3.1: system message 提到顶层。"""
    body = json.dumps({
        "model": "claude-3-5-haiku",
        "messages": [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 100,
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert adapted["system"] == "You are helpful"
    # messages 里不再有 system role
    assert all(m["role"] != "system" for m in adapted["messages"])
    assert adapted["messages"] == [{"role": "user", "content": "hi"}]
    assert adapted["max_tokens"] == 100


def test_adapt_preserves_multiple_system_messages():
    """多个 system message 合并到顶层。"""
    body = json.dumps({
        "model": "claude-3-5-haiku",
        "messages": [
            {"role": "system", "content": "rule 1"},
            {"role": "system", "content": "rule 2"},
            {"role": "user", "content": "go"},
        ],
    }).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert "rule 1" in adapted["system"]
    assert "rule 2" in adapted["system"]


def test_adapt_noop_for_openai_format():
    """OpenAI 格式不转换。"""
    body = b'{"model":"gpt-4o","messages":[]}'
    assert byok_router.adapt_request_body(body, "openai") == body


def test_adapt_adds_max_tokens_default():
    """无 max_tokens 时补默认值（Anthropic 必填）。"""
    body = json.dumps({"model": "claude-3-5-haiku", "messages": []}).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert "max_tokens" in adapted
    assert adapted["max_tokens"] > 0


def test_adapt_preserves_stream_flag():
    body = json.dumps({"model": "claude-3-5-haiku", "messages": [], "stream": True}).encode()
    adapted = json.loads(byok_router.adapt_request_body(body, "anthropic"))
    assert adapted["stream"] is True
