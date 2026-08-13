"""Region detection (three levels: config → IP probe → locale fallback).

See design doc §16.2 (N3-M3).
IP probing enables more accurate region determination
(CN → tokeneff.com, overseas → global.tokeneff.com);
falls back to locale on failure.
"""

from __future__ import annotations

import locale
import os

import httpx

from . import config as cfg_module

# IP probe services (in priority order), return JSON with a country field
_IP_PROBES = [
    "https://ipapi.co/json/",       # {country: "CN"}
    "https://ip-api.com/json/",     # {countryCode: "CN"}
]
_PROBE_TIMEOUT = 3.0


def detect_region() -> str:
    """Detect the user's region, returns 'cn' or 'global'.

    Three-level detection: config.region (explicit user setting) → IP probe → locale fallback.
    """
    cfg = cfg_module.get_config()
    if cfg.region in ("cn", "global"):
        return cfg.region

    # IP probe (more accurate; falls back to locale on failure)
    region = _detect_via_ip()
    if region:
        return region

    return _detect_via_locale()


def _detect_via_ip() -> str | None:
    """Probe via public IP geolocation.

    Returns:
        'cn' / 'global' / None (probe failed)
    """
    for url in _IP_PROBES:
        try:
            with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                country = (data.get("country") or data.get("countryCode") or "").upper()
                if country == "CN":
                    return "cn"
                if country:  # has an explicit country and not CN
                    return "global"
        except Exception:
            continue
    return None


def _detect_via_locale() -> str:
    """Fallback via system locale.

    ★ N-m2: locale.getdefaultlocale() is deprecated since 3.11; use getlocale() + env vars.
    """
    try:
        loc = locale.getlocale()[0] or os.environ.get("LANG", "") or os.getenv("LC_ALL", "")
        loc = (loc or "").lower()
        if loc.startswith("zh"):
            return "cn"
    except Exception:
        pass
    return "global"
