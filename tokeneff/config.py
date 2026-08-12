"""tokeneff 配置管理。

配置存 ~/.tokeneff/config.toml（非敏感字段），
API key 存系统 keyring（敏感字段，明文不落盘）。

关联设计文档 §4.5、§16.3（H-NEW-2 合并版 TokenEffConfig）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import tomlkit

try:
    import keyring
    # 探测后端可用性：无 DBus/桌面环境时 SecretService 写入会抛 KeyringLocked，
    # 探测失败则降级到 keyrings.alt 文件后端（纯本地文件，无需桌面服务）。
    try:
        keyring.set_password("tokeneff-probe", "probe", "probe")
        keyring.delete_password("tokeneff-probe", "probe")
    except Exception:
        try:
            from keyrings.alt.file import PlaintextKeyring
            keyring.set_keyring(PlaintextKeyring())
        except Exception:
            pass
except ImportError:  # keyring 可能在某些无桌面环境不可用
    keyring = None

CONFIG_DIR = Path.home() / ".tokeneff"
CONFIG_PATH = CONFIG_DIR / "config.toml"
KEYRING_SERVICE = "tokeneff"
KEYRING_PLATFORM = "tokeneff-platform-key"

_config: Optional["TokenEffConfig"] = None


@dataclass
class TokenEffConfig:
    """tokeneff 配置（敏感 key 不在此，走 keyring）。"""

    mode: str = "byok"  # "byok" | "platform"
    region: str = ""  # "" | "cn" | "global"
    platform_url: str = ""
    platform_key_ref: str = ""  # keyring 引用名（占位，实际 key 在 keyring）
    budget_monthly_usd: float = 0.0  # 统一预算字段（CN 也存 USD，展示层换算 ¥）
    alert_threshold: float = 0.8
    proxy_port: int = 7860

    def get_platform_url(self) -> str:
        if self.platform_url:
            return self.platform_url
        if self.region == "cn":
            return "https://tokeneff.com"
        return "https://global.tokeneff.com"

    def get_currency(self) -> str:
        """根据 region 返回计费货币（CN→CNY，否则 USD）。"""
        return "CNY" if self.region == "cn" else "USD"

    def get_budget(self) -> float:
        return self.budget_monthly_usd


# ── keyring 读写 ──────────────────────────────────────────────────────────────


def _kr_get(account: str) -> Optional[str]:
    if keyring is None:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, account)
    except Exception:
        return None


def _kr_set(account: str, value: str) -> None:
    if keyring is None:
        return
    try:
        keyring.set_password(KEYRING_SERVICE, account, value)
    except Exception:
        pass  # 无 keyring 后端时静默降级（开发环境）


def get_api_key(provider: str) -> Optional[str]:
    return _kr_get(f"byok:{provider}")


def set_api_key(provider: str, key: str) -> None:
    _kr_set(f"byok:{provider}", key)


def get_platform_key() -> Optional[str]:
    return _kr_get(KEYRING_PLATFORM)


def set_platform_key(key: str) -> None:
    _kr_set(KEYRING_PLATFORM, key)


# ── 配置文件读写 ──────────────────────────────────────────────────────────────


def save(cfg: "TokenEffConfig") -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    # 不写敏感字段
    data.pop("platform_key_ref", None)
    doc = tomlkit.document()
    for k, v in data.items():
        doc[k] = v
    CONFIG_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")


def load(force: bool = False) -> "TokenEffConfig":
    global _config
    if _config is not None and not force:
        return _config
    if CONFIG_PATH.exists():
        try:
            doc = tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))
            _config = TokenEffConfig(**{k: v.unwrap() if hasattr(v, "unwrap") else v
                                        for k, v in doc.items()})
            return _config
        except Exception:
            pass
    _config = TokenEffConfig()
    return _config


def get_config() -> "TokenEffConfig":
    return load()
