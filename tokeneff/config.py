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

    def get_budget_in(self, currency: str | None = None) -> float:
        """Budget converted to the display currency (★ H1 audit fix).

        budget_monthly_usd is always stored in USD (wizard converts ¥ input ÷ rate).
        Display must match the meter's currency: CNY users see the ¥ equivalent.
        """
        cur = currency or self.get_currency()
        if cur == "CNY":
            from .meter.collector import USD_CNY_RATE
            return self.budget_monthly_usd * USD_CNY_RATE
        return self.budget_monthly_usd

    def set_region(self, region: str) -> None:
        """Set region and cascade platform_url + currency (★ R1 引流转化方案).

        Called after onboarding region confirmation. Auto-configures the gateway
        URL for the detected region (cn→tokeneff.com, global→global.tokeneff.com).
        Does NOT overwrite a user-customized platform_url — only resets it when
        empty or still at a default value.
        """
        self.region = region
        defaults = ("", "https://tokeneff.com", "https://global.tokeneff.com")
        if self.platform_url in defaults:
            self.platform_url = (
                "https://tokeneff.com" if region == "cn"
                else "https://global.tokeneff.com"
            )


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
    """Load config from ~/.tokeneff/config.toml.

    ★ M13 fix (audit): a corrupt file or unknown key (e.g. written by a newer
    version) previously raised inside TokenEffConfig(**...) and was silently
    swallowed — the user's region/budget reset to defaults and could then be
    overwritten by the next save. Now: unknown keys are dropped (forward
    compat), and a parse failure backs up the file to .bak with a warning
    instead of silently discarding everything.
    """
    global _config
    if _config is not None and not force:
        return _config
    if CONFIG_PATH.exists():
        import dataclasses
        import logging
        import shutil

        logger = logging.getLogger("tokeneff.config")
        try:
            doc = tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))
            valid_fields = {f.name for f in dataclasses.fields(TokenEffConfig)}
            unknown = [k for k in doc.keys() if k not in valid_fields]
            if unknown:
                logger.warning(f"config.toml has unknown keys (newer version?), ignored: {unknown}")
            _config = TokenEffConfig(**{
                k: (v.unwrap() if hasattr(v, "unwrap") else v)
                for k, v in doc.items() if k in valid_fields
            })
            return _config
        except Exception as e:
            # Back up the corrupt file so nothing is silently lost, then fall
            # back to defaults (the backup preserves manual recovery).
            try:
                backup = CONFIG_PATH.with_suffix(".toml.bak")
                shutil.copy2(CONFIG_PATH, backup)
                logger.warning(
                    f"config.toml parse failed ({e}); reset to defaults. "
                    f"Original backed up to {backup}"
                )
            except Exception:
                logger.warning(f"config.toml parse failed ({e}); reset to defaults (backup also failed)")
    _config = TokenEffConfig()
    return _config


def get_config() -> "TokenEffConfig":
    return load()
