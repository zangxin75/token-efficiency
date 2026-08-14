"""Sidecar read-only meter API (Plan A §3.1).

Serves the Tauri frontend polling for meter data. Shares the collector global singleton
with the proxy (★ H2), ensuring buffered data written by the proxy is immediately readable
by the sidecar (not two separate SQLite connections).

Port (★ M1): default 7861, probes incrementally when occupied; the actual port is returned via /api/health.
Binds only to 127.0.0.1 loopback to reduce AV false positives.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .. import config as cfg_module
from ..meter.collector import collector  # ★ H2: shared global singleton
from ..meter.predictor import SpendPredictor
from ..port_finder import find_free_port

log = logging.getLogger("tokeneff.sidecar")

DEFAULT_API_PORT = 7861


async def _periodic_flush():
    """★ M5: periodic flush fallback to shrink the crash-loss window.

    The store batch buffer only flushes at 50 records; an abnormal crash would lose unflushed buffer.
    This task forces a flush every 30s, shrinking the loss window from "up to 50 records" to "within 30s".
    WAL mode guarantees already-flushed data is not corrupted.
    """
    while True:
        await asyncio.sleep(30)
        try:
            await collector.store.flush()
        except Exception as e:
            log.warning(f"periodic flush failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ★ H2: reuse the global collector singleton; idempotent if the proxy already init'd
    await collector.init()
    # ★ M5: start the periodic flush to shrink the crash-loss window
    flush_task = asyncio.create_task(_periodic_flush())
    log.info("tokeneff sidecar API ready (shared collector, 30s flush guard)")
    try:
        yield
    finally:
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass
        await collector.close()


app = FastAPI(title="tokeneff Sidecar API", version="0.1.0", lifespan=lifespan)

# Use a regex to cover tauri origins (local-only sources, tightened)
# ★ B2 regression fix (Windows integration pitfall): the Tauri dev server origin carries a dynamic port
# (e.g. http://127.0.0.1:1420); a fixed allow_origins allowlist cannot cover it.
# Lesson: "logs show 200" does not mean "the frontend got the data" — responses without CORS headers are dropped by the webview.
# ★ B5 regression fix (installer pitfall): Tauri 2 production-mode origin varies by webview —
#   Windows WebView2 = https://tauri.localhost; macOS/Linux WebKit = tauri://localhost.
#   The original ^tauri:// only matched WebKit, missing WebView2, so the installer's fetchSummary was blocked by CORS and the ball stayed grey.
# ★ review fix: the old regex allowed ANY 127.0.0.1/localhost port as origin — any local
#   page could POST /api/config/key and overwrite keyring keys or flip platform_url to an
#   attacker-controlled gateway (key exfiltration). Production now accepts only the two
#   tauri origins. Dev (vite server on http://127.0.0.1:142x) is detected via
#   PyInstaller's frozen flag instead of an env var — the sidecar is spawned by Tauri as
#   a child process and SIDECAR_DEV could not be injected through `tauri dev`, leaving
#   the dev ball grey (verified: Origin http://127.0.0.1:1420 got no allow-origin header).
import os
import sys as _sys


def _sys_env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


_TAURI_ORIGINS = r"^https?://tauri\.localhost$|^tauri://"
_DEV_LOOPBACK = r"|^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
# Dev escape hatch, in priority order:
# 1. source-run (python -m / pytest): frozen=False
# 2. `tauri dev` spawns the PACKAGED exe (frozen=True!) but is a debug build —
#    the Rust sidecar spawner sets SIDECAR_DEV=1 only for cfg!(debug_assertions)
#    builds (verified tauri-plugin-shell 2.3.5 has Command::env; spawning inherits
#    the parent env which `tauri dev` does NOT customize, so an explicit flag is
#    required). Release/NSIS builds never set it — production CORS stays tight.
_IS_DEV = not getattr(_sys, "frozen", False) or _sys_env_flag("SIDECAR_DEV")
if _IS_DEV:
    _ORIGIN_REGEX = _TAURI_ORIGINS + _DEV_LOOPBACK
else:
    _ORIGIN_REGEX = _TAURI_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_ORIGIN_REGEX,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── health check (returns the actual port for frontend handshake) ───────────────


@app.get("/api/health")
async def health():
    cfg = cfg_module.get_config()
    return {
        "status": "ok",
        "version": "0.1.0",
        "proxy_port": cfg.proxy_port,
        "mode": cfg.mode,
        "region": cfg.region,
        "currency": cfg.get_currency(),
    }


# ── meter read-only endpoints ──────────────────────────────────────────────────


@app.get("/api/meter/summary")
async def meter_summary():
    """Today / month / forecast / savings / rate summary."""
    cfg = cfg_module.get_config()
    currency = cfg.get_currency()
    store = collector.store  # ★ H2: the singleton's store

    today = await store.get_today_total(currency=currency)
    month = await store.get_month_total(currency=currency)
    rate = await store.get_recent_rate(currency=currency)
    saved = await store.get_total_saved(currency=currency)
    history = await store.get_history_30d()
    forecast = SpendPredictor(store).predict_monthly(history, currency)
    budget = cfg.get_budget()
    # ★ contract fix: month is in the region currency (CNY for cn) while
    # budget_monthly_usd is USD — dividing directly inflated the ratio ~7.2x,
    # turning the ball red at ~11% real usage. Convert budget into the same
    # currency before computing the percentage (ratio only, display budget stays USD).
    from ..meter.calculator import USD_TO_CNY
    budget_in_currency = budget * USD_TO_CNY if currency == "CNY" else budget
    budget_pct = (month / budget_in_currency * 100) if budget_in_currency > 0 else None

    return {
        "currency": currency,
        "today": today,
        "month": month,
        "rate_per_min": rate,
        "saved": saved,
        "budget": budget,
        "budget_pct": budget_pct,
        # ★ 阈值联动 UI：前端球色/预算条跟随用户配置（不再硬编码 60/80 分界）
        "alert_threshold": cfg.alert_threshold,
        "forecast": {
            "estimated": forecast.estimated,
            "current_spend": forecast.current_spend,
            "daily_avg": forecast.daily_avg,
            "confidence": forecast.confidence,
        },
    }


@app.get("/api/meter/models")
async def meter_models():
    """Today's model breakdown."""
    cfg = cfg_module.get_config()
    breakdown = await collector.store.get_model_breakdown_today(
        currency=cfg.get_currency()
    )
    return {"models": breakdown}


@app.get("/api/meter/history")
async def meter_history(days: int = 30):
    """Historical trend (aggregated per day)."""
    days = max(1, min(days, 90))
    currency = cfg_module.get_config().get_currency()
    history = await collector.store.get_history_30d()
    # ★ review fix: filter by the region currency before aggregating — a region
    # switch (cn↔global) would otherwise mix CNY and USD amounts into the same
    # daily totals, silently inflating or shrinking the trend chart ~7x
    by_day: dict[str, dict] = {}
    for r in history:
        if r.currency != currency:
            continue
        day = r.timestamp[:10]
        d = by_day.setdefault(day, {"date": day, "charged": 0.0, "saved": 0.0, "tokens": 0})
        d["charged"] += r.charged_amount
        d["saved"] += r.saved_amount
        d["tokens"] += r.input_tokens + r.output_tokens
    series = sorted(by_day.values(), key=lambda x: x["date"])
    return {"days": days, "currency": currency, "series": series}


# ── config read/write ──────────────────────────────────────────────────────────


@app.get("/api/config")
async def get_config():
    cfg = cfg_module.get_config()
    # ★ contract fix: iterate the live registry — the old hardcoded 6-tuple missed
    # moonshot, so users with only a moonshot key were flagged as unconfigured and
    # re-onboarded on every launch
    from ..proxy.model_registry import PROVIDER_REGISTRY
    providers = [p for p in PROVIDER_REGISTRY if cfg_module.get_api_key(p)]
    return {
        "mode": cfg.mode,
        "region": cfg.region,
        # ★ manual-override lock: frontend auto-detect respects this and never
        # rewrites a manually chosen region; only "重新检测" clears it
        "region_manual": cfg.region_manual,
        "currency": cfg.get_currency(),
        "proxy_port": cfg.proxy_port,
        "budget_monthly_usd": cfg.budget_monthly_usd,
        "alert_threshold": cfg.alert_threshold,
        "providers_configured": providers,
        "has_platform_key": cfg_module.get_platform_key() is not None,
        "platform_url": cfg.platform_url,
    }


@app.get("/api/region/detect")
async def detect_region_api():
    """Region detection signals + recommendation (★ R1 onboarding display).

    Multi-signal weighted (timezone primary, VPN-proof; IP secondary).
    ★ M4 fix (audit): detection does blocking network IO (2 probes × 3s timeout) —
    run in a thread pool so the event loop (and every other polling endpoint)
    keeps serving; cache the result for 5 minutes (signals barely change).
    """
    import time as _time

    from ..region import detect_region_signals

    now = _time.monotonic()
    cached = getattr(detect_region_api, "_cache", None)
    if cached and now - cached[0] < 300:
        return cached[1]

    import anyio

    sig = await anyio.to_thread.run_sync(detect_region_signals)
    result = {
        "timezone": sig.timezone,
        "locale": sig.locale,
        "ip_country": sig.ip_country,
        "win_locale": sig.win_locale,
        "cn_score": sig.cn_score,
        "global_score": sig.global_score,
        "recommended": sig.recommended,  # "cn"/"global"/None(borderline→confirm)
        "reason": sig.reason,
    }
    detect_region_api._cache = (now, result)
    return result


@app.get("/api/providers")
async def list_providers():
    """Available provider list (★ B3 onboarding dropdown use; avoids hardcoding in the frontend).

    Generated dynamically from PROVIDER_REGISTRY, marking which are already configured (keyring has a key).
    """
    from ..proxy.model_registry import PROVIDER_REGISTRY

    result = []
    for name, info in PROVIDER_REGISTRY.items():
        result.append({
            "name": name,
            "label": info.get("label", name),
            "models": info.get("models", [])[:5],  # show the first 5 default models
            "auth_header": info.get("auth_header", "authorization"),
            "configured": cfg_module.get_api_key(name) is not None,
        })
    return {"providers": result}


def _validate_gateway_url(url: str) -> tuple[bool, str]:
    """Platform gateway URL whitelist (★ M7 audit fix: anti-SSRF / anti-key-exfil).

    A malicious local process (or a poisoned localhost webpage via a simple-request POST)
    could previously set platform_url to an attacker host — the proxy would then send the
    user's platform key there as a Bearer token; /api/config/platform-verify could also be
    used as an intranet port-scan oracle. Now: only https://*.tokeneff.com official domains
    plus localhost (dev) are accepted.
    """
    import re as _re

    url = (url or "").strip().rstrip("/")
    if not url:
        return False, "URL is empty"
    m = _re.match(r"^https?://([^/:]+)", url)
    if not m:
        return False, "URL must start with http(s)://"
    host = m.group(1).lower()
    # Local dev allowed (plain http OK on loopback only)
    if host in ("localhost", "127.0.0.1", "::1"):
        return True, url
    if not url.startswith("https://"):
        return False, "External gateway must use https://"
    if host == "tokeneff.com" or host.endswith(".tokeneff.com"):
        return True, url
    return False, f"Non-official gateway domain: {host} (risk of platform-key exfiltration)"


def _parse_octet(host: str, index: int) -> int:
    """host like '172.16.x.x' → int of the octet at `index`; 0 on parse failure."""
    try:
        return int(host.split(".")[index])
    except (ValueError, IndexError):
        return 0


class ConfigUpdatePayload(BaseModel):
    """★ review fix: update_config previously took a raw dict with zero validation —
    budget_monthly_usd:"abc" would poison config.toml and permanently 500 every
    /api/meter/summary; platform_url accepted arbitrary URLs that the platform mode
    would send the gateway key to as a Bearer header."""

    model_config = {"extra": "ignore"}

    mode: Optional[str] = None
    region: Optional[str] = None
    # ★ manual-override lock flag (sent together with region by the frontend:
    # manual save sets True, explicit re-detect sets False)
    region_manual: Optional[bool] = None
    platform_url: Optional[str] = None
    budget_monthly_usd: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    # percent 10-100 (the Settings slider range); legacy 0-1 values are normalized
    # in TokenEffConfig.__post_init__ — a le=10 bound here silently 422'd every
    # normal slider value and killed the whole budget form (contract review find)
    alert_threshold: Optional[float] = Field(default=None, ge=0, le=100)
    proxy_port: Optional[int] = Field(default=None, ge=1024, le=65535)

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("byok", "platform"):
            raise ValueError("mode must be 'byok' or 'platform'")
        return v

    @field_validator("region")
    @classmethod
    def _check_region(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().lower()
            if v not in ("cn", "global"):
                raise ValueError("region must be 'cn' or 'global'")
        return v

    @field_validator("platform_url")
    @classmethod
    def _check_platform_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return v  # empty = fall back to region default, allowed
        # The platform key is sent to this URL as a Bearer header (platform_router);
        # require https, and reject loopback/private/link-local hosts — verified
        # during testing that https://127.0.0.1 previously passed and the key would
        # be delivered to any local https service.
        if not v.startswith("https://") or len(v) <= len("https://"):
            raise ValueError("platform_url must start with https://")
        from urllib.parse import urlparse

        host = (urlparse(v).hostname or "").lower()
        blocked = (
            host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
            or host.startswith("127.")
            or host.startswith("10.")
            or host.startswith("192.168.")
            or host.startswith("169.254.")
            or (host.startswith("172.") and 16 <= _parse_octet(host, 1) <= 31)
        )
        if blocked:
            raise ValueError("platform_url 不能指向本机或内网地址")
        return v


@app.post("/api/config")
async def update_config(payload: ConfigUpdatePayload):
    """Update non-sensitive config (mode/region/budget/proxy_port/alert_threshold).

    Sensitive keys go through a separate endpoint (/api/config/key); only non-sensitive fields here.
    Invalid values are rejected with 422 by the Pydantic model instead of poisoning config.toml.
    """
    cfg = cfg_module.get_config()
    changed: dict = {}
    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        if not hasattr(cfg, k):
            continue
        if k == "region":
            # region cascades platform_url + currency via set_region (★ R3 frontend wiring:
            # a bare setattr would bypass the cascade, leaving platform_url stale and key
            # verification hitting the wrong gateway). Mirrors the CLI wizard's behavior.
            cfg.set_region(v)
            changed["region"] = cfg.region
            changed["platform_url"] = cfg.platform_url
        else:
            setattr(cfg, k, v)
            changed[k] = v

    if changed:
        cfg_module.save(cfg)
        cfg_module.load(force=True)  # clear cache
    # "errors" kept empty for response-shape compatibility (older clients read it)
    return {"updated": changed, "errors": {}}


@app.post("/api/config/key")
async def set_provider_key(payload: dict):
    """Store a provider API key into keyring (never written to disk in plaintext).

    payload: {"provider": "glm", "key": "sk-..."}
    """
    provider = payload.get("provider")
    key = payload.get("key")
    if not provider or not key:
        return {"ok": False, "error": "provider 和 key 必填"}
    if not cfg_module.set_api_key(provider, key):
        # ★ review fix: no secure keyring backend → refuse instead of silently
        # losing the key (previously the failure was swallowed and "ok" lied)
        return {"ok": False, "error": "无可用安全密钥库（keyring），key 未存储。桌面环境或凭据管理器不可用。"}
    # Read back to verify (★ H1: keyring packaging failures surface here)
    stored = cfg_module.get_api_key(provider)
    return {"ok": stored == key, "provider": provider}


@app.post("/api/config/verify")
async def verify_provider_key(payload: dict):
    """Verify whether an API key is valid (★ B3 onboarding use: verify before saving the key).

    payload: {"provider": "glm", "key": "sk-..."}
    Reuses byok_router.verify_key (probes upstream per the provider's auth_header + GET/POST).

    Returns:
        {"ok": bool, "message": str}  ok=true means the key is valid
    """
    from ..proxy.byok_router import verify_key

    provider = payload.get("provider")
    key = payload.get("key")
    if not provider or not key:
        return {"ok": False, "message": "provider 和 key 必填"}
    try:
        valid, message = await verify_key(provider, key)
        return {"ok": valid, "message": message}
    except Exception as e:
        return {"ok": False, "message": f"验证请求失败: {e}"}


@app.post("/api/config/platform-verify")
async def verify_platform_key(payload: dict):
    """Verify a tokeneff gateway platform key (★ B3.1).

    payload: {"key": "...", "platform_url": "https://tokeneff.com"}  # platform_url optional
    Probes the gateway via GET /v1/models; an invalid key returns 401.

    Returns:
        {"ok": bool, "message": str}
    """
    import httpx

    key = payload.get("key")
    if not key:
        return {"ok": False, "message": "key 必填"}
    cfg = cfg_module.get_config()
    # Allow the body to temporarily specify a url (verify an unsaved gateway address); otherwise use configured/default
    base_raw = payload.get("platform_url") or cfg.get_platform_url()
    # ★ M7: whitelist the probe URL — this endpoint must not become an intranet port-scan oracle
    ok, msg = _validate_gateway_url(base_raw)
    if not ok:
        return {"ok": False, "message": f"网关地址不被允许: {msg}"}
    base = base_raw.strip().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base}/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 200:
            return {"ok": True, "message": "网关 key 有效"}
        if resp.status_code in (401, 403):
            return {"ok": False, "message": f"网关拒绝（{resp.status_code}），key 无效或已过期"}
        return {"ok": False, "message": f"网关返回 {resp.status_code}"}
    except httpx.ConnectError:
        return {"ok": False, "message": f"无法连接网关 {base}（网络或地址错误）"}
    except Exception as e:
        return {"ok": False, "message": f"验证请求失败: {e}"}


@app.post("/api/config/platform-key")
async def set_platform_key(payload: dict):
    """Store a tokeneff gateway platform key into keyring (★ B3.1; never written to disk in plaintext).

    payload: {"key": "..."}
    Symmetric with the BYOK /api/config/key: read back to verify after storing.
    """
    key = payload.get("key")
    if not key:
        return {"ok": False, "error": "key 必填"}
    if not cfg_module.set_platform_key(key):
        return {"ok": False, "error": "无可用安全密钥库（keyring），key 未存储。桌面环境或凭据管理器不可用。"}
    stored = cfg_module.get_platform_key()
    return {"ok": stored == key, "has_platform_key": stored is not None}


# ── startup entry point ────────────────────────────────────────────────────────


def run_sidecar(host: str = "127.0.0.1", preferred_port: int = DEFAULT_API_PORT) -> int:
    """Start the sidecar API; return the actual port (★ M1: port auto-discovery)."""
    actual_port = find_free_port(preferred_port, host=host)
    if actual_port != preferred_port:
        log.warning(f"port {preferred_port} occupied, sidecar switched to {actual_port}")
    log.info(f"tokeneff sidecar API → http://{host}:{actual_port}/api")
    uvicorn.run(app, host=host, port=actual_port, log_level="info")
    return actual_port


if __name__ == "__main__":
    run_sidecar()
