"""Sidecar 只读电表 API（方案A §3.1）。

供 Tauri 前端轮询拉取电表数据。与 proxy 共享 collector 全局单例（★ H2），
确保 proxy 写入的缓冲数据能被 sidecar 立即读到（非双 SQLite 连接）。

端口（★ M1）：默认 7861，被占用时递增探测，实际端口通过 /api/health 返回。
仅绑定 127.0.0.1 回环，降低杀软误报。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import config as cfg_module
from ..meter.collector import collector  # ★ H2: 共享全局单例
from ..meter.predictor import SpendPredictor
from ..port_finder import find_free_port

log = logging.getLogger("tokeneff.sidecar")

DEFAULT_API_PORT = 7861


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ★ H2: 复用全局 collector 单例；若 proxy 已 init 则幂等
    await collector.init()
    log.info("tokeneff sidecar API ready (shared collector singleton)")
    yield
    await collector.close()


app = FastAPI(title="tokeneff Sidecar API", version="0.1.0", lifespan=lifespan)

# 仅允许本机回环来源（前端是同机 WebView），收紧 CORS
# ★ dev 模式 webview origin 带 vite 端口（如 http://127.0.0.1:1420），生产为 tauri://localhost
# 用正则一次覆盖回环任意端口，避免 dev/prod 分别配置
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^tauri://localhost$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── 健康检查（返回实际端口，供前端握手）─────────────────────────────────────────


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


# ── 电表只读接口 ───────────────────────────────────────────────────────────────


@app.get("/api/meter/summary")
async def meter_summary():
    """今日/本月/预测/节省/速率 汇总。"""
    cfg = cfg_module.get_config()
    currency = cfg.get_currency()
    store = collector.store  # ★ H2: 共享单例的 store

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
    """今日模型分布。"""
    breakdown = await collector.store.get_model_breakdown_today()
    return {"models": breakdown}


@app.get("/api/meter/history")
async def meter_history(days: int = 30):
    """历史趋势（按天聚合）。"""
    days = max(1, min(days, 90))
    history = await collector.store.get_history_30d()
    # 按天聚合
    by_day: dict[str, dict] = {}
    for r in history:
        day = r.timestamp[:10]
        d = by_day.setdefault(day, {"date": day, "charged": 0.0, "saved": 0.0, "tokens": 0})
        d["charged"] += r.charged_amount
        d["saved"] += r.saved_amount
        d["tokens"] += r.input_tokens + r.output_tokens
    series = sorted(by_day.values(), key=lambda x: x["date"])
    return {"days": days, "series": series}


# ── 配置读写 ───────────────────────────────────────────────────────────────────


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
    }


@app.post("/api/config")
async def update_config(payload: dict):
    """更新非敏感配置（mode/region/budget/proxy_port/alert_threshold）。

    敏感 key 走单独端点（/api/config/key），此处仅非敏感字段。
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
        cfg_module.load(force=True)  # 清缓存
    return {"updated": changed}


@app.post("/api/config/key")
async def set_provider_key(payload: dict):
    """存 provider API key 到 keyring（明文不落盘）。

    payload: {"provider": "glm", "key": "sk-..."}
    """
    provider = payload.get("provider")
    key = payload.get("key")
    if not provider or not key:
        return {"ok": False, "error": "provider 和 key 必填"}
    cfg_module.set_api_key(provider, key)
    # 读回验证（★ H1: keyring 打包失效时会在这里暴露）
    stored = cfg_module.get_api_key(provider)
    return {"ok": stored == key, "provider": provider}


# ── 启动入口 ───────────────────────────────────────────────────────────────────


def run_sidecar(host: str = "127.0.0.1", preferred_port: int = DEFAULT_API_PORT) -> int:
    """启动 sidecar API，返回实际端口（★ M1: 端口自适应）。"""
    actual_port = find_free_port(preferred_port, host=host)
    if actual_port != preferred_port:
        log.warning(f"端口 {preferred_port} 被占用，sidecar 改用 {actual_port}")
    log.info(f"tokeneff sidecar API → http://{host}:{actual_port}/api")
    uvicorn.run(app, host=host, port=actual_port, log_level="info")
    return actual_port


if __name__ == "__main__":
    run_sidecar()
