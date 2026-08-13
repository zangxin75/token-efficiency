"""tokeneff configuration management.

Non-sensitive config is stored in ~/.tokeneff/config.toml;
API keys are stored in the system keyring (sensitive, never written to disk in plaintext).

See design doc §4.5, §16.3 (H-NEW-2 merged TokenEffConfig).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import tomlkit

try:
    import keyring
    # Probe backend availability: without DBus/desktop environment SecretService
    # writes raise KeyringLocked; on probe failure fall back to keyrings.alt file
    # backend (plain local file, no desktop service required).
    try:
        keyring.set_password("tokeneff-probe", "probe", "probe")
        keyring.delete_password("tokeneff-probe", "probe")
    except Exception:
        try:
            from keyrings.alt.file import PlaintextKeyring
            keyring.set_keyring(PlaintextKeyring())
        except Exception:
            pass
except ImportError:  # keyring may be unavailable in some headless environments
    keyring = None

CONFIG_DIR = Path.home() / ".tokeneff"
CONFIG_PATH = CONFIG_DIR / "config.toml"
KEYRING_SERVICE = "tokeneff"
KEYRING_PLATFORM = "tokeneff-platform-key"

_config: Optional["TokenEffConfig"] = None


@dataclass
class TokenEffConfig:
    """tokeneff configuration (sensitive keys are not stored here; they go to keyring)."""

    mode: str = "byok"  # "byok" | "platform"
    region: str = ""  # "" | "cn" | "global"
    platform_url: str = ""
    platform_key_ref: str = ""  # keyring reference name (placeholder; actual key lives in keyring)
    budget_monthly_usd: float = 0.0  # unified budget field (CN also stores USD; display layer converts to ¥)
    alert_threshold: float = 0.8
    proxy_port: int = 7860

    def get_platform_url(self) -> str:
        if self.platform_url:
            return self.platform_url
        if self.region == "cn":
            return "https://tokeneff.com"
        return "https://global.tokeneff.com"

    def get_currency(self) -> str:
        """Return the billing currency based on region (CN→CNY, otherwise USD)."""
        return "CNY" if self.region == "cn" else "USD"

    def get_budget(self) -> float:
        return self.budget_monthly_usd


# ── keyring read/write ──────────────────────────────────────────────────────────


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
        pass  # silently degrade when no keyring backend available (dev environment)


def get_api_key(provider: str) -> Optional[str]:
    return _kr_get(f"byok:{provider}")


def set_api_key(provider: str, key: str) -> None:
    _kr_set(f"byok:{provider}", key)


def get_platform_key() -> Optional[str]:
    return _kr_get(KEYRING_PLATFORM)


def set_platform_key(key: str) -> None:
    _kr_set(KEYRING_PLATFORM, key)


# ── config file read/write ──────────────────────────────────────────────────────


def save(cfg: "TokenEffConfig") -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    # Do not write sensitive fields
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
