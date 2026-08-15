"""Meter display: rich table output.

CLI/TUI output language follows the region (same policy as the desktop app's
i18n): global → English, otherwise Chinese. Overseas users with a Chinese
system locale but a global account see English.
"""

from __future__ import annotations


def _is_en() -> bool:
    try:
        from .. import config as cfg_module

        return cfg_module.get_config().region == "global"
    except Exception:
        return False


def L(zh: str, en: str) -> str:
    """Pick the output label by region: global → en, else zh."""
    return en if _is_en() else zh
