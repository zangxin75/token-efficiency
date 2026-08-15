"""BYOK routing: the user brings their own key and connects to upstream directly.

See design doc §4.3 (route + auth_header) + §4.3.1 (adapt_request_body) + §5.2 (verify_key).
Revisions: N-C3 (auth_header) / N3-C3 (verify POST) / N3-C2 (adapt wiring).
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
    """model → provider (exact match first, then prefix match)."""
    if model in MODEL_TO_PROVIDER:
        return MODEL_TO_PROVIDER[model]
    # Prefix match (e.g. gpt-4o-2024-08-06)
    for provider, info in PROVIDER_REGISTRY.items():
        for m in info.get("models", []):
            if model.startswith(m) or m.startswith(model.split("-")[0]):
                return provider
    return None


def route(model: str, body: bytes, request_headers: dict) -> tuple[str, dict]:
    """Return (upstream_url, headers). Build the auth header per the provider's auth_header.

    ★ N-C3 revision: Anthropic uses x-api-key; others use Authorization: Bearer.
    ★ review fix: unknown model + no matching provider key in keyring now raises —
    previously the client's own Authorization header was forwarded to api.openai.com
    by guesswork, leaking e.g. a GLM key to an unrelated upstream (one-way disclosure).
    """
    provider_name = _resolve_provider(model)
    if provider_name is None:
        # Unknown model: default to OpenAI-compatible
        provider_name = "openai"
    provider = PROVIDER_REGISTRY[provider_name]

    # Get this provider's key from keyring
    user_key = cfg_module.get_api_key(provider_name)
    if not user_key:
        if provider_name == "openai" and _resolve_provider(model) is None:
            # Unknown model AND no OpenAI key stored: forwarding the client's own
            # credentials to a guessed upstream is a key leak — refuse instead.
            raise ByokRouterError(
                f"unknown model '{model}' and no key stored for the fallback provider; "
                " refusing to forward client credentials to a guessed upstream"
            )
        # Known provider without a stored key: fall back to the request's Authorization
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
    """★ §4.3.1 / N3-C2: OpenAI → Anthropic format conversion.

    The user sends requests via the OpenAI SDK, but Anthropic/Kimi-Coding use
    /v1/messages (Anthropic format). Convert OpenAI messages (including the system role)
    into Anthropic's top-level system + messages.

    ★ 透传策略（review fix）：原实现只构造 7 个白名单字段，tools/tool_choice/
    top_p/stop/n 等被静默剥离——OpenAI SDK 带工具的请求会静默失效。现在以原文
    为基础，仅改写语义冲突的字段（system role 上提、max_tokens 必填），未知
    字段原样保留，由上游决定接受或报错。
    """
    if provider_format != "anthropic":
        return body
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body

    out: dict = dict(data)  # passthrough base: keep tools/tool_choice/top_p/stop/n/...
    messages = data.get("messages", [])

    # Peel the system message out to the top level (Anthropic: system is top-level, not a role)
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    if system_parts:
        out["system"] = "\n\n".join(str(p) for p in system_parts)
    out["messages"] = [m for m in messages if m.get("role") != "system"]

    # ★ review fix: OpenAI 专属字段 Anthropic 会以 400 拒绝（透传策略不能只"保留"，
    # 语义冲突的字段必须改写或剔除，否则带 stop/n/penalties 的请求全部失败）
    # stop: OpenAI 接受 str|list，Anthropic 只认 stop_sequences: list
    if "stop" in out:
        stop = out.pop("stop")
        if isinstance(stop, str):
            out["stop_sequences"] = [stop]
        elif isinstance(stop, list):
            out["stop_sequences"] = stop
    # n/penalties/logit_bias 等 OpenAI 采样参数在 Anthropic 无对应语义 → 剔除
    for k in ("n", "frequency_penalty", "presence_penalty", "logit_bias",
              "logprobs", "top_logprobs", "response_format", "seed",
              "stream_options", "parallel_tool_calls", "user", "service_tier"):
        out.pop(k, None)

    # tools: OpenAI {"type":"function","function":{name,description,parameters}}
    #     → Anthropic {"name","description","input_schema"}（已是 Anthropic 形状的保留）
    if isinstance(out.get("tools"), list):
        converted = []
        for t in out["tools"]:
            fn = t.get("function") if isinstance(t, dict) else None
            if fn and t.get("type") == "function":
                converted.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object"}),
                })
            else:
                converted.append(t)
        out["tools"] = converted
    # tool_choice: auto 同名直通; function→tool(带 name); required→any; none→移除
    if "tool_choice" in out:
        tc = out["tool_choice"]
        if isinstance(tc, dict):
            t = tc.get("type")
            if t == "function":
                out["tool_choice"] = {"type": "tool", "name": tc.get("function", {}).get("name", "")}
            elif t == "required":
                out["tool_choice"] = {"type": "any"}
            elif t == "none":
                out.pop("tool_choice", None)
                out.pop("tools", None)

    # max_tokens is required by Anthropic
    if "max_tokens" not in out:
        out["max_tokens"] = 4096

    return json.dumps(out).encode("utf-8")


def get_provider_format(model: str) -> str:
    """Return the format (openai/anthropic) of the provider for the given model."""
    provider_name = _resolve_provider(model)
    if provider_name is None:
        return "openai"
    return PROVIDER_REGISTRY[provider_name].get("format", "openai")


async def verify_key(provider: str, api_key: str) -> tuple[bool, str]:
    """Verify whether an API key is valid.

    ★ N-C3 + N3-C3: build the header per auth_header, choose GET/POST per verify_method.
    Anthropic /v1/messages is POST-only (GET returns 405, falsely reporting the key as invalid).
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
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            if verify_method == "post":
                probe_body = {
                    "model": info["models"][0],
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                }
                resp = await client.post(url, headers=headers, json=probe_body)
            else:
                resp = await client.get(url, headers=headers)
        # 200=valid; 429=valid but rate-limited; 401=invalid; 403=no permission
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
