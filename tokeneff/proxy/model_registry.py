"""Model registry: provider name → endpoint / auth / format mapping.

See design doc §4.2 (model_registry) + N-C3 revision (auth_header).
"""

from typing import TypedDict


class ProviderInfo(TypedDict, total=False):
    base_url: str
    register_url: str
    key_prefix: str
    models: list[str]
    verify_endpoint: str
    endpoint_path: str
    format: str  # "openai" | "anthropic"
    auth_header: str  # "authorization" | "x-api-key"
    verify_method: str  # "get" | "post"
    headers: dict  # provider-specific headers (e.g., anthropic-version)


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

PROVIDER_REGISTRY: dict[str, ProviderInfo] = {
    # ── OpenAI ───────────────────────────────────────────────────────────────
    "openai": {
        "base_url": "https://api.openai.com",
        "register_url": "https://platform.openai.com/api-keys",
        "key_prefix": "sk-",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "verify_endpoint": "/v1/models",
        "endpoint_path": "/v1/chat/completions",
        "format": "openai",
        "auth_header": "authorization",
        "verify_method": "get",
    },
    # ── DeepSeek ─────────────────────────────────────────────────────────────
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "register_url": "https://platform.deepseek.com/api-keys",
        "key_prefix": "sk-",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-coder"],
        "verify_endpoint": "/v1/models",
        "endpoint_path": "/v1/chat/completions",
        "format": "openai",
        "auth_header": "authorization",
        "verify_method": "get",
    },
    # ── GLM ────────────────────────────────────────────────────────────────
    "glm": {
        "base_url": "https://open.bigmodel.cn",
        "register_url": "https://open.bigmodel.cn/dev/apikeys",
        "key_prefix": "",
        "models": ["glm-4-flash", "glm-4-plus", "glm-4", "glm-3-flash"],
        "verify_endpoint": "/api/paas/v4/models",
        "endpoint_path": "/api/paas/v4/chat/completions",
        "format": "openai",
        "auth_header": "authorization",
        "verify_method": "get",
    },
    # ── Kimi Coding（api.kimi.com/coding/）────────────────────────────────
    "kimi_coding": {
        "base_url": "https://api.kimi.com",
        "register_url": "https://platform.kimi.com/console/api-keys",
        "key_prefix": "sk-kimi-",
        "models": ["kimi-k2.6", "kimi-k2.7-code", "kimi-k2.5"],
        "verify_endpoint": "/kimi/coding/v1/models",
        "endpoint_path": "/kimi/coding/v1/messages",
        "format": "anthropic",  # Anthropic-compatible protocol
        "auth_header": "x-api-key",  # ★ N-C3 revision
        "verify_method": "post",  # ★ N3-C3 revision
        "headers": {"anthropic-version": "2023-06-01"},
    },
    # ── Kimi Platform（api.moonshot.cn）──────────────────────────────────
    "moonshot": {
        "base_url": "https://api.moonshot.cn",
        "register_url": "https://platform.kimi.com/console/api-keys",
        "key_prefix": "sk-kimi-",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "verify_endpoint": "/v1/models",
        "endpoint_path": "/v1/chat/completions",
        "format": "openai",
        "auth_header": "authorization",
        "verify_method": "get",
    },
    # ── MiniMax ────────────────────────────────────────────────────────────
    "minimax": {
        "base_url": "https://api.minimaxi.com",
        "register_url": "https://platform.minimaxi.com/home/api-keys",
        "key_prefix": "",
        "models": ["minimax-m3", "minimax-m2.5"],
        "verify_endpoint": "/v1/text/chatcompletion_v2",
        "endpoint_path": "/v1/text/chatcompletion_v2",
        "format": "openai",
        "auth_header": "authorization",
        "verify_method": "get",
    },
    # ── Anthropic（Claude）───────────────────────────────────────────────
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "register_url": "https://console.anthropic.com/settings/keys",
        "key_prefix": "sk-ant-",
        "models": ["claude-sonnet-4-6", "claude-3-5-haiku", "claude-3-opus"],
        "verify_endpoint": "/v1/messages",
        "endpoint_path": "/v1/messages",
        "format": "anthropic",
        "auth_header": "x-api-key",  # ★ N-C3 revision
        "verify_method": "post",  # ★ N3-C3 revision: GET /v1/messages returns 405
        "headers": {"anthropic-version": "2023-06-01"},
    },
}

# ── reverse index: model → provider (faster lookups) ───────────────────────────
MODEL_TO_PROVIDER: dict[str, str] = {}
for provider, info in PROVIDER_REGISTRY.items():
    for model in info.get("models", []):
        MODEL_TO_PROVIDER[model] = provider
