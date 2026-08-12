"""地域检测（三级：config → IP 探测 → locale 兜底）。

关联设计文档 §16.2（N3-M3）。
IP 探测用于更精准的地域判定（国内 → tokeneff.com，海外 → global.tokeneff.com），
失败时降级到 locale。
"""

from __future__ import annotations

import locale
import os

import httpx

from . import config as cfg_module

# IP 探测服务（按优先级），返回 JSON 含 country 字段
_IP_PROBES = [
    "https://ipapi.co/json/",       # {country: "CN"}
    "https://ip-api.com/json/",     # {countryCode: "CN"}
]
_PROBE_TIMEOUT = 3.0


def detect_region() -> str:
    """检测用户地域，返回 'cn' 或 'global'。

    三级检测：config.region（用户显式设置）→ IP 探测 → locale 兜底。
    """
    cfg = cfg_module.get_config()
    if cfg.region in ("cn", "global"):
        return cfg.region

    # IP 探测（更精准，失败降级 locale）
    region = _detect_via_ip()
    if region:
        return region

    return _detect_via_locale()


def _detect_via_ip() -> str | None:
    """通过公网 IP 归属地探测。

    Returns:
        'cn' / 'global' / None（探测失败）
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
                if country:  # 有明确国家且非 CN
                    return "global"
        except Exception:
            continue
    return None


def _detect_via_locale() -> str:
    """通过系统语言环境兜底。

    ★ N-m2：locale.getdefaultlocale() 自 3.11 废弃，改 getlocale() + 环境变量。
    """
    try:
        loc = locale.getlocale()[0] or os.environ.get("LANG", "") or os.getenv("LC_ALL", "")
        loc = (loc or "").lower()
        if loc.startswith("zh"):
            return "cn"
    except Exception:
        pass
    return "global"
