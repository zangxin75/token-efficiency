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

# 用正则覆盖任意回环端口 + tauri scheme（仅本机来源，收紧）
# ★ B2 回流修复（Windows 联调踩坑）：Tauri dev server 的 origin 带动态端口
# （如 http://127.0.0.1:1420），固定白名单 allow_origins 无法覆盖，改用正则。
# 教训："日志显示 200"不等于"前端拿到数据"——无 CORS 头的响应会被 webview 丢弃。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$|^tauri://",
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


@app.get("/api/providers")
async def list_providers():
    """可用 provider 列表（★ B3 onboarding 下拉用，避免前端硬编码）。

    从 PROVIDER_REGISTRY 动态生成，标记哪些已配置（keyring 有 key）。
    """
    from ..proxy.model_registry import PROVIDER_REGISTRY

    result = []
    for name, info in PROVIDER_REGISTRY.items():
        result.append({
            "name": name,
            "label": info.get("label", name),
            "models": info.get("models", [])[:5],  # 展示前 5 个默认模型
            "auth_header": info.get("auth_header", "authorization"),
            "configured": cfg_module.get_api_key(name) is not None,
        })
    return {"providers": result}


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


@app.post("/api/config/verify")
async def verify_provider_key(payload: dict):
    """验证 API key 是否有效（★ B3 onboarding 用：配 key 前先验证）。

    payload: {"provider": "glm", "key": "sk-..."}
    复用 byok_router.verify_key（按 provider 的 auth_header + GET/POST 探测上游）。

    Returns:
        {"ok": bool, "message": str}  ok=true 表示 key 有效
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
