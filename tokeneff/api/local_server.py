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

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# Use a regex to cover any loopback port + tauri scheme (local-only sources, tightened)
# ★ B2 regression fix (Windows integration pitfall): the Tauri dev server origin carries a dynamic port
# (e.g. http://127.0.0.1:1420); a fixed allow_origins allowlist cannot cover it, so use a regex.
# Lesson: "logs show 200" does not mean "the frontend got the data" — responses without CORS headers are dropped by the webview.
# ★ B5 regression fix (installer pitfall): Tauri 2 production-mode origin varies by webview —
#   Windows WebView2 = https://tauri.localhost; macOS/Linux WebKit = tauri://localhost.
#   The original ^tauri:// only matched WebKit, missing WebView2, so the installer's fetchSummary was blocked by CORS and the ball stayed grey.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$|^https?://tauri\.localhost$|^tauri://",
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
    rate = await store.get_recent_rate()
    saved = await store.get_total_saved()
    history = await store.get_history_30d()
    forecast = SpendPredictor(store).predict_monthly(history, currency)
    budget = cfg.get_budget()

    return {
        "currency": currency,
        "today": today,
        "month": month,
        "rate_per_min": rate,
        "saved": saved,
        "budget": budget,
        "budget_pct": (month / budget * 100) if budget > 0 else None,
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
    breakdown = await collector.store.get_model_breakdown_today()
    return {"models": breakdown}


@app.get("/api/meter/history")
async def meter_history(days: int = 30):
    """Historical trend (aggregated per day)."""
    days = max(1, min(days, 90))
    history = await collector.store.get_history_30d()
    # Aggregate per day
    by_day: dict[str, dict] = {}
    for r in history:
        day = r.timestamp[:10]
        d = by_day.setdefault(day, {"date": day, "charged": 0.0, "saved": 0.0, "tokens": 0})
        d["charged"] += r.charged_amount
        d["saved"] += r.saved_amount
        d["tokens"] += r.input_tokens + r.output_tokens
    series = sorted(by_day.values(), key=lambda x: x["date"])
    return {"days": days, "series": series}


# ── config read/write ──────────────────────────────────────────────────────────


@app.get("/api/config")
async def get_config():
    cfg = cfg_module.get_config()
    providers = [p for p in ("openai", "deepseek", "glm", "kimi_coding", "minimax", "anthropic")
                 if cfg_module.get_api_key(p)]
    return {
        "mode": cfg.mode,
        "region": cfg.region,
        "currency": cfg.get_currency(),
        "proxy_port": cfg.proxy_port,
        "budget_monthly_usd": cfg.budget_monthly_usd,
        "alert_threshold": cfg.alert_threshold,
        "providers_configured": providers,
        "has_platform_key": cfg_module.get_platform_key() is not None,
        "platform_url": cfg.platform_url,
    }


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


@app.post("/api/config")
async def update_config(payload: dict):
    """Update non-sensitive config (mode/region/budget/proxy_port/alert_threshold).

    Sensitive keys go through a separate endpoint (/api/config/key); only non-sensitive fields here.
    """
    cfg = cfg_module.get_config()
    allowed = {"mode", "region", "budget_monthly_usd", "proxy_port", "alert_threshold", "platform_url"}
    changed = {}
    for k, v in payload.items():
        if k in allowed and hasattr(cfg, k):
            setattr(cfg, k, v)
            changed[k] = v
    if changed:
        cfg_module.save(cfg)
        cfg_module.load(force=True)  # clear cache
    return {"updated": changed}


@app.post("/api/config/key")
async def set_provider_key(payload: dict):
    """Store a provider API key into keyring (never written to disk in plaintext).

    payload: {"provider": "glm", "key": "sk-..."}
    """
    provider = payload.get("provider")
    key = payload.get("key")
    if not provider or not key:
        return {"ok": False, "error": "provider 和 key 必填"}
    cfg_module.set_api_key(provider, key)
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
    base = (payload.get("platform_url") or cfg.get_platform_url()).rstrip("/")
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
    cfg_module.set_platform_key(key)
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
