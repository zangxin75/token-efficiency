"""平台模式路由器（§4.4）：转发到 TokenEff gateway。

平台模式 = 用 TokenEff 网关的 key，一个 key 通吃多模型，按量计费。
透明计费：本地计算"官方价 vs 我们价"，展示 saved 归因（§15.2）。

与 BYOK 的区别：
- BYOK：用户自己的 key，直连上游，0 加价（charged == official）
- 平台：TokenEff 网关 key，转发到 gateway，charged 按我们定价，saved > 0
"""

from __future__ import annotations

from .. import config as cfg_module
from .byok_router import adapt_request_body, get_provider_format


def route(model: str, body: bytes, request_headers: dict) -> tuple[str, dict]:
    """平台模式路由：转发到 TokenEff gateway。

    Args:
        model: 模型名
        body: 请求体（bytes）
        request_headers: 客户端原始请求头（忽略，用平台 key）

    Returns:
        (url, headers) 网关地址 + 平台 key 头

    Raises:
        RuntimeError: 未配置平台 key
    """
    cfg = cfg_module.get_config()
    platform_key = cfg_module.get_platform_key()
    if not platform_key:
        raise RuntimeError(
            "平台模式未配置 key。请运行 `tokeneff setup` 选择平台模式，"
            "或前往网关注册获取 key。"
        )

    base = cfg.get_platform_url().rstrip("/")
    url = f"{base}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {platform_key}",
    }
    return url, headers


def get_format(model: str) -> str:
    """平台模式统一走 OpenAI 兼容（网关侧负责转换）。

    但客户端发的可能是 Anthropic 格式（claude 模型），需按客户端格式 adapt。
    """
    return get_provider_format(model)


def adapt_body(model: str, body: bytes) -> bytes:
    """平台模式：按目标模型格式 adapt（网关是 OpenAI 兼容入口）。

    客户端 → 网关统一 OpenAI 格式。若客户端发 Anthropic 格式且模型是 claude，
    网关侧会处理；本地不做额外转换（与 BYOK 的 adapt 语义不同）。
    """
    fmt = get_provider_format(model)
    # 网关入口统一 OpenAI 兼容，Anthropic 模型也由网关转换
    # 但若客户端明确发 anthropic 格式，本地仍提 system（与 BYOK 一致）
    if fmt == "anthropic":
        return adapt_request_body(body, "anthropic")
    return adapt_request_body(body, "openai")
