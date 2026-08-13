"""Platform-mode router (§4.4): forwards to the TokenEff gateway.

Platform mode = use the TokenEff gateway key; one key covers all models, billed per usage.
Transparent billing: locally computes "official price vs our price", surfaces saved attribution (§15.2).

Difference vs BYOK:
- BYOK: the user's own key, connects directly to upstream, 0 markup (charged == official)
- Platform: TokenEff gateway key, forwarded to the gateway, charged per our pricing, saved > 0
"""

from __future__ import annotations

from .. import config as cfg_module
from .byok_router import adapt_request_body, get_provider_format


def route(model: str, body: bytes, request_headers: dict, path: str = "") -> tuple[str, dict]:
    """Platform-mode routing: forward to the TokenEff gateway.

    Args:
        model: model name
        body: request body (bytes)
        request_headers: original client request headers (ignored; platform key is used instead)
        path: client request path (e.g. "v1/messages", "v1/chat/completions")
              ★ Forward to the gateway's same-named endpoint per the client endpoint;
              protocol format is decided by the endpoint, not the model name
              (alias mapping may let an Anthropic client send a glm-* model name).

    Returns:
        (url, headers) gateway URL + platform key header

    Raises:
        RuntimeError: platform key not configured
    """
    cfg = cfg_module.get_config()
    platform_key = cfg_module.get_platform_key()
    if not platform_key:
        raise RuntimeError(
            "平台模式未配置 key。请运行 `tokeneff setup` 选择平台模式，"
            "或前往网关注册获取 key。"
        )

    base = cfg.get_platform_url().rstrip("/")

    # ★ Pass through the client path: the gateway supports both /v1/messages and
    # /v1/chat/completions; forward in the client's original format to avoid sending
    # an Anthropic body to an OpenAI endpoint.
    # Only allowlist known LLM endpoints; everything else defaults to chat/completions (backward compat).
    suffix = path.lstrip("/")
    if suffix in ("v1/messages", "v1/chat/completions", "v1/responses"):
        url = f"{base}/{suffix}"
    else:
        url = f"{base}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {platform_key}",
    }
    return url, headers


def get_format(model: str, client_endpoint: str = "") -> str:
    """Platform-mode format detection: ★ by client endpoint, not model name.

    Hitting /v1/messages = Anthropic client (Claude Code), return "anthropic";
    otherwise decide by model name (compatible with OpenAI SDK clients).
    """
    if "messages" in client_endpoint:
        return "anthropic"
    return get_provider_format(model)


def adapt_body(model: str, body: bytes) -> bytes:
    """Platform mode: adapt per the target model's format (the gateway is an OpenAI-compatible entry point).

    Client → gateway uniformly OpenAI format. If the client sends Anthropic format and the model
    is claude, the gateway side handles it; no extra conversion locally (different semantics from BYOK adapt).
    """
    fmt = get_provider_format(model)
    # The gateway entry point is uniformly OpenAI-compatible; Anthropic models are converted by the gateway too
    # But if the client explicitly sends anthropic format, locally still lift system out (consistent with BYOK)
    if fmt == "anthropic":
        return adapt_request_body(body, "anthropic")
    return adapt_request_body(body, "openai")
