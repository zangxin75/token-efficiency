"""BYOK 路由：用户自带 key 直连上游。

关联设计文档 §4.3（route + auth_header）+ §4.3.1（adapt_request_body）+ §5.2（verify_key）。
修订：N-C3（auth_header）/ N3-C3（verify POST）/ N3-C2（adapt 接线）。
"""

from __future__ import annotations

import json
from typing import Optional

import httpx

from .. import config as cfg_module
from .model_registry import MODEL_TO_PROVIDER, PROVIDER_REGISTRY


class ByokRouterError(Exception):
    pass


def _resolve_provider(model: str) -> Optional[str]:
    """model → provider（先精确匹配，再前缀匹配）。"""
    if model in MODEL_TO_PROVIDER:
        return MODEL_TO_PROVIDER[model]
    # 前缀匹配（如 gpt-4o-2024-08-06）
    for provider, info in PROVIDER_REGISTRY.items():
        for m in info.get("models", []):
            if model.startswith(m) or m.startswith(model.split("-")[0]):
                return provider
    return None


def route(model: str, body: bytes, request_headers: dict) -> tuple[str, dict]:
    """返回 (upstream_url, headers)。按 provider 的 auth_header 构造认证头。

    ★ N-C3 修订：Anthropic 用 x-api-key，其他用 Authorization: Bearer。
    """
    provider_name = _resolve_provider(model)
    if provider_name is None:
        # 未知模型：默认当 openai 兼容，用请求自带的 Authorization
        provider_name = "openai"
    provider = PROVIDER_REGISTRY[provider_name]

    # 从 keyring 取该 provider 的 key
    user_key = cfg_module.get_api_key(provider_name)
    if not user_key:
        # 兜底：用请求头自带的 Authorization
        auth = request_headers.get("authorization", "") or request_headers.get("Authorization", "")
        user_key = auth[7:].strip() if auth.lower().startswith("bearer ") else auth

    auth_header = provider.get("auth_header", "authorization")
    headers = {"Content-Type": "application/json"}
    if auth_header == "x-api-key":
        headers["x-api-key"] = user_key
    else:
        headers["Authorization"] = f"Bearer {user_key}"
    if extra := provider.get("headers"):
        headers.update(extra)

    upstream_url = f"{provider['base_url']}{provider['endpoint_path']}"
    return upstream_url, headers


def adapt_request_body(body: bytes, provider_format: str) -> bytes:
    """★ §4.3.1 / N3-C2：OpenAI ↔ Anthropic 格式转换。

    用户用 OpenAI SDK 发请求，但 Anthropic/Kimi-Coding 用 /v1/messages（Anthropic 格式）。
    需把 OpenAI 的 messages（含 system role）转成 Anthropic 的顶层 system + messages。
    """
    if provider_format != "anthropic":
        return body
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body

    out: dict = {"model": data.get("model")}
    messages = data.get("messages", [])

    # 剥离 system message 到顶层
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    if system_parts:
        out["system"] = "\n\n".join(str(p) for p in system_parts)
    out["messages"] = [m for m in messages if m.get("role") != "system"]

    # max_tokens 在 Anthropic 是必填
    out["max_tokens"] = data.get("max_tokens", 4096)
    if "temperature" in data:
        out["temperature"] = data["temperature"]
    if data.get("stream"):
        out["stream"] = True

    return json.dumps(out).encode("utf-8")


def get_provider_format(model: str) -> str:
    """返回 model 对应 provider 的 format（openai/anthropic）。"""
    provider_name = _resolve_provider(model)
    if provider_name is None:
        return "openai"
    return PROVIDER_REGISTRY[provider_name].get("format", "openai")


async def verify_key(provider: str, api_key: str) -> tuple[bool, str]:
    """验证 API key 是否有效。

    ★ N-C3 + N3-C3：按 auth_header 构造头，按 verify_method 选 GET/POST。
    Anthropic /v1/messages 是 POST-only（GET 会 405 误报 key 无效）。
    """
    info = PROVIDER_REGISTRY.get(provider)
    if not info:
        return False, f"unknown provider: {provider}"

    url = f"{info['base_url']}{info['verify_endpoint']}"
    auth_header = info.get("auth_header", "authorization")
    headers = {"Content-Type": "application/json"}
    if auth_header == "x-api-key":
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra := info.get("headers"):
        headers.update(extra)

    verify_method = info.get("verify_method", "get")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if verify_method == "post":
                probe_body = {
                    "model": info["models"][0],
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                }
                resp = await client.post(url, headers=headers, json=probe_body)
            else:
                resp = await client.get(url, headers=headers)
        # 200=有效；429=有效但限流；401=无效；403=无权限
        if resp.status_code in (200, 429):
            return True, "✅ Key verified"
        elif resp.status_code == 401:
            return False, "❌ Invalid API key"
        elif resp.status_code == 403:
            return False, "❌ Key valid but no permission"
        else:
            return False, f"❌ Unexpected: HTTP {resp.status_code}"
    except httpx.TimeoutException:
        return False, "❌ Timeout (Chinese APIs may need VPN)"
    except Exception as e:
        return False, f"❌ Error: {e}"
