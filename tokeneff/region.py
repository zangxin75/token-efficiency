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
    # Windows localized tzname fallback (Chinese-locale systems)
    "中国标准时间", "中国夏令时",
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
    1. /etc/timezone (Debian IANA name) or /etc/localtime symlink (macOS/Fedora/Arch)
    2. Windows registry TimeZoneKeyName
    3. tzname fallback (last resort; localized names like 中国标准时间 handled in set)
    """
    # 1a. Debian/Ubuntu: /etc/timezone gives IANA name (e.g. "Asia/Shanghai")
    try:
        with open("/etc/timezone") as f:
            tz = f.read().strip()
            if tz:
                return tz
    except Exception:
        pass
    # 1b. macOS/Fedora/Arch/RHEL: resolve /etc/localtime symlink → .../zoneinfo/Asia/Shanghai
    try:
        import re as _re
        link = os.path.realpath("/etc/localtime")
        m = _re.search(r"zoneinfo[/\\](.+)$", link)
        if m:
            return m.group(1)  # e.g. "Asia/Shanghai"
    except Exception:
        pass
    # 2. Windows: registry TimeZoneKeyName (e.g. "China Standard Time")
    # ★ audit fix: raw string must use SINGLE backslashes — r"...\\..." embeds literal
    # double backslashes and winreg.OpenKey fails silently (Chinese-Windows users all
    # misrouted to global via the cascade this caused).
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
            ) as k:
                tz, _ = winreg.QueryValueEx(k, "TimeZoneKeyName")
                if tz:
                    return tz
        except Exception:
            pass
    # 3. Fallback: tzname (may be ambiguous CST or localized 中国标准时间 — both in set)
    try:
        return time.tzname[0] if time.tzname else ""
    except Exception:
        return ""


def _detect_locale() -> str:
    """System locale (LC_ALL > LANG > LC_CTYPE), normalized for zh detection.

    ★ audit fixes: ① LC_ALL has higher priority than LANG (order was reversed);
    ② Windows returns localized names like "Chinese (Simplified)_China" which do
    not start with "zh" — normalize to "zh_cn" so the zh signal fires.
    """
    try:
        loc = (
            locale.getlocale()[0]
            or os.getenv("LC_ALL", "")
            or os.environ.get("LANG", "")
        )
        loc = (loc or "").lower()
        # Windows localized locale name → normalize to a zh_ prefix
        if loc.startswith("chinese"):
            return "zh_cn"
        return loc
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
                # ★ H3 fix (audit): parse BOTH probe response shapes.
                # myip.ipip.net returns {"ret":"ok","data":{"location":["中国","辽宁",...]}}
                #   — the country is nested at data.location[0], NOT top-level "country"
                #   (the old code never matched → the CN-reachable first probe was dead code).
                # ipinfo.io returns {"country":"CN"} at top level.
                country = (data.get("country") or data.get("countryCode") or "")
                if not country:
                    loc_list = (data.get("data") or {}).get("location") or []
                    if loc_list:
                        country = str(loc_list[0])  # e.g. "中国"
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
    # ★ M6 fix (audit): borderline fallback uses the TIMEZONE signal, not locale.
    # zh-TW/zh-HK/zh-SG users have zh locales but non-CN timezones — falling back to
    # locale routed them to the cn site (ICP/Alipay) against intent. Timezone matches
    # the website's geo.js verdict, keeping client and website consistent.
    return "cn" if sig.timezone in _CN_TIMEZONES else "global"
