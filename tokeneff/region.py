"""Region detection — multi-signal weighted (R1 upgrade).

Penetrates VPN: timezone + locale (which VPN can't change) are primary signals;
IP is secondary (unreliable under VPN). Borderline cases force user confirmation.

★ Upgrade from old version (IP-first → VPN-spoofed). Mirrors the global-site
geo.js logic (timezone China → cn) so client and website agree.

See design doc §16.2 + 引流转化改造方案_区域识别与网关注册引导.
"""

from __future__ import annotations

import locale
import os
import time
from dataclasses import dataclass

import httpx

from . import config as cfg_module

# China timezones (IANA names + Windows names — reliable, unambiguous;
# unlike tzname "CST" which is ambiguous between China UTC+8 and US Central UTC-6)
_CN_TIMEZONES = {
    # IANA (Linux/macOS)
    "Asia/Shanghai", "Asia/Urumqi", "Asia/Chongqing", "Asia/Chungking",
    "Asia/Harbin", "PRC",
    # Windows TimeZoneKeyName
    "China Standard Time", "China Daylight Time",
}

# IP probe services — must be reachable from mainland China (ipapi.co/ip-api.com are blocked).
# IP is a weak signal under VPN; these are best-effort only.
_IP_PROBES = [
    "https://myip.ipip.net/json",   # {country: "中国"} — China-reachable
    "https://ipinfo.io/json",       # {country: "CN"}    — China-reachable
]
_PROBE_TIMEOUT = 3.0


@dataclass
class RegionSignals:
    """Raw region signals + weighted recommendation (for onboarding display)."""
    timezone: str = ""            # IANA name, e.g. "Asia/Shanghai"
    locale: str = ""              # e.g. "zh_CN"
    ip_country: str | None = None  # "CN" / "US" / None (probe failed)
    win_locale: str | None = None  # Windows system locale (Win only), e.g. "zh-CN"
    cn_score: int = 0
    global_score: int = 0
    recommended: str | None = None  # "cn" / "global" / None (insufficient → force confirm)
    reason: str = ""                # human-readable basis for onboarding


def _detect_timezone() -> str:
    """Get timezone name (IANA on Linux/macOS, Windows name on Win). VPN cannot change this.

    ★ Avoid tzname() 'CST' — ambiguous (China UTC+8 vs US Central UTC-6). Prefer:
    1. /etc/timezone (Linux IANA name)
    2. Windows registry TimeZoneKeyName
    3. tzname fallback (last resort, flagged ambiguous)
    """
    # 1. Linux: /etc/timezone gives IANA name (e.g. "Asia/Shanghai")
    try:
        with open("/etc/timezone") as f:
            tz = f.read().strip()
            if tz:
                return tz
    except Exception:
        pass
    # 2. Windows: registry TimeZoneKeyName (e.g. "China Standard Time")
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\\CurrentControlSet\\Control\\TimeZoneInformation",
            ) as k:
                tz, _ = winreg.QueryValueEx(k, "TimeZoneKeyName")
                if tz:
                    return tz
        except Exception:
            pass
    # 3. Fallback: tzname (may be ambiguous CST — combined with locale/offset in scoring)
    try:
        return time.tzname[0] if time.tzname else ""
    except Exception:
        return ""


def _detect_locale() -> str:
    """System locale (LC_CTYPE / LANG / LC_ALL)."""
    try:
        loc = locale.getlocale()[0] or os.environ.get("LANG", "") or os.getenv("LC_ALL", "")
        return (loc or "").lower()
    except Exception:
        return ""


def _detect_win_locale() -> str | None:
    """Windows system locale via ctypes (Win only). VPN can't change."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(85)
        ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85)
        return buf.value or None  # e.g. "zh-CN"
    except Exception:
        return None


def _detect_ip_country() -> str | None:
    """Public IP geolocation. Best-effort (VPN-spoofable, often blocked in CN)."""
    for url in _IP_PROBES:
        try:
            with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                country = (data.get("country") or data.get("countryCode") or "")
                # myip.ipip.net returns Chinese name "中国"
                if "中国" in country or country.upper() == "CN":
                    return "CN"
                if country:
                    return country.upper()
        except Exception:
            continue
    return None


def detect_region_signals() -> RegionSignals:
    """Collect all region signals and compute weighted recommendation.

    Weights (★ mirrors global-site geo.js so client & website agree):
    - Timezone (IANA China) +3   ← primary, VPN-proof
    - Locale (zh*)            +2
    - IP == CN                +1   ← weak under VPN
    - Windows locale (zh)     +2

    Verdict: |cn - global| > 2 → recommend winner; else None (force user confirm).
    """
    sig = RegionSignals()
    sig.timezone = _detect_timezone()
    sig.locale = _detect_locale()
    sig.ip_country = _detect_ip_country()
    sig.win_locale = _detect_win_locale()

    is_cn_tz = sig.timezone in _CN_TIMEZONES
    is_cn_locale = sig.locale.startswith("zh")
    is_cn_win = bool(sig.win_locale and sig.win_locale.lower().startswith("zh"))

    if is_cn_tz:
        sig.cn_score += 3
    else:
        sig.global_score += 1
    if is_cn_locale:
        sig.cn_score += 2
    else:
        sig.global_score += 1
    if sig.ip_country == "CN":
        sig.cn_score += 1
    elif sig.ip_country:
        sig.global_score += 1
    if is_cn_win:
        sig.cn_score += 2
    elif sig.win_locale:
        sig.global_score += 1

    # Verdict: clear lead → recommend; tie/low signal → None (force confirm)
    diff = sig.cn_score - sig.global_score
    if diff > 2:
        sig.recommended = "cn"
    elif diff < -2:
        sig.recommended = "global"
    else:
        sig.recommended = None  # borderline → let user decide

    sig.reason = _build_reason(sig, is_cn_tz, is_cn_locale, is_cn_win)
    return sig


def _build_reason(sig, is_cn_tz, is_cn_locale, is_cn_win) -> str:
    """Human-readable basis for onboarding display."""
    parts = []
    parts.append(f"timezone={sig.timezone}({'CN' if is_cn_tz else 'non-CN'})")
    parts.append(f"locale={sig.locale or '?'}({'zh' if is_cn_locale else 'non-zh'})")
    if sig.ip_country:
        parts.append(f"ip={sig.ip_country}")
    if sig.win_locale:
        parts.append(f"win={sig.win_locale}")
    parts.append(f"score cn={sig.cn_score}/global={sig.global_score}")
    if sig.recommended:
        parts.append(f"→ {sig.recommended}")
    else:
        parts.append("→ borderline (confirm)")
    return " | ".join(parts)


def recommend_region() -> tuple[str | None, str]:
    """Return (recommended region or None, reason text). Force-confirm on borderline."""
    sig = detect_region_signals()
    return sig.recommended, sig.reason


def detect_region() -> str:
    """Detect region (backward-compat). Returns 'cn' or 'global'.

    Explicit config wins. Otherwise multi-signal recommend; borderline defaults
    to locale (safer than guessing wrong pricing tier).
    """
    cfg = cfg_module.get_config()
    if cfg.region in ("cn", "global"):
        return cfg.region

    sig = detect_region_signals()
    if sig.recommended:
        return sig.recommended
    # Borderline: fall back to locale signal (avoid forcing in non-interactive contexts)
    return "cn" if sig.locale.startswith("zh") else "global"
