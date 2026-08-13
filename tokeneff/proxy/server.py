"""本地代理服务器：FastAPI 拦截请求 → BYOK 路由 → 上游 → 计费 → 响应。

关联设计文档 §3.3（intercept）+ N3-C2（adapt 接线）。
非流式：请求 → 转发 → 完整响应 → extract_usage → calculate → record。
流式：请求 → 转发 → aiter_raw 逐块 → UsageAccumulator → finally record。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from . import byok_router, platform_router
from .. import config as cfg_module
from ..meter.collector import collector
from ..meter.types import UsageResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tokeneff.server")

app = FastAPI(title="tokeneff BYOK Proxy", version="0.1.0")

# 挂载的子应用路径（如 /v1/）
MOUNT_PREFIX = "/v1"


@app.on_event("startup")
async def startup():
    await collector.init()
    log.info("tokeneff collector initialized")


@app.on_event("shutdown")
async def shutdown():
    await collector.close()
    log.info("tokeneff collector closed")


def _extract_model(body: dict) -> str:
    return body.get("model", "unknown")


def _is_stream_request(body: dict) -> bool:
    return body.get("stream", False) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 拦截入口
# ═══════════════════════════════════════════════════════════════════════════════


@app.api_route("/{path:path}", methods=["POST"])
async def intercept(request: Request, path: str):
    """拦截所有 POST 请求（/v1/chat/completions 等）。

    流程：route → adapt(anthropic) → 上游 → 计费 → 返回。
    """
    # 1. 解析请求体
    body = await request.body()
    try:
        body_json = json.loads(body)
    except json.JSONDecodeError:
        return Response(content="Invalid JSON", status_code=400)

    model = _extract_model(body_json)
    mode = cfg_module.get_config().mode  # "byok" | "platform"

    # 2. 路由：按 mode 分支选择 BYOK（用户 key 直连上游）或平台（TokenEff 网关）
    req_headers = dict(request.headers)
    if mode == "platform":
        # ★ 透传 path：Claude Code 打 /v1/messages，需转发到网关同名端点
        upstream_url, headers = platform_router.route(model, body, req_headers, path)
        provider_format = "openai"  # ★ platform 模式不做本地 adapt，网关自处理格式转换
    else:
        upstream_url, headers = byok_router.route(model, body, req_headers)
        provider_format = byok_router.get_provider_format(model)

    # 3. Anthropic 格式转换（★ N3-C2，仅 BYOK 模式；platform 模式网关侧转换）
    if provider_format == "anthropic":
        body = byok_router.adapt_request_body(body, provider_format)

    is_stream = _is_stream_request(body_json)

    # 4. 转发到上游
    start_time = time.time()
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            upstream_req = client.build_request(
                "POST", upstream_url, content=body, headers=headers,
            )
            upstream_resp = await client.send(upstream_req, stream=is_stream)
        except Exception as e:
            log.error(f"upstream error: {e}")
            return Response(content=f"Upstream error: {e}", status_code=502)

    # 5. 处理响应：非流式 vs 流式
    if is_stream:
        return StreamingResponse(
            _stream_and_meter(upstream_resp, model, mode, start_time),
            media_type=upstream_resp.headers.get("content-type", "application/json"),
        )
    else:
        # 非流式：全量读 → 计费 → 写入
        content = await upstream_resp.aread()
        elapsed = time.time() - start_time

        if upstream_resp.status_code != 200:
            return Response(
                content=content,
                status_code=upstream_resp.status_code,
                headers=dict(upstream_resp.headers),
            )

        # 解析 usage，计算成本，记录
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return Response(content=content, status_code=200)

        usage = UsageResult.from_dict(payload)
        if usage.has_data:
            await collector.record(model, usage, elapsed=elapsed)
            log.info(f"[metered] {model}: in={usage.input_tokens} out={usage.completion_tokens}, elapsed={elapsed:.2f}s")

        return Response(
            content=content,
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
        )


async def _stream_and_meter(upstream_resp, model: str, mode: str, start_time: float):
    """流式响应：逐块透传 + 可选 usage 采集。

    简化版 MVP：直接透传上游流，不做实时推送（v0.1 无 TUI Live）。
    流式 usage 解析依赖上游在末 chunk 返回 usage（OpenAI 兼容），否则不计入。
    """
    accumulated = b""
    async for chunk in upstream_resp.aiter_raw():
        accumulated += chunk
        yield chunk

    # 流结束，尝试从末 chunk 解析 usage
    elapsed = time.time() - start_time
    try:
        # 末 chunk 可能是 data: {...}\n\n
        for line in accumulated.decode("utf-8").split("\n"):
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    continue
                data = json.loads(data_str)
                usage = UsageResult.from_dict(data)
                if usage.has_data:
                    await collector.record(model, usage, elapsed=elapsed)
                    log.info(f"[metered stream] {model}: in={usage.input_tokens} out={usage.completion_tokens}")
                    break
    except Exception as e:
        log.warning(f"stream usage parse error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ═══════════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════════


def run(host: str = "127.0.0.1", port: int = 7860):
    import uvicorn
    log.info(f"Starting tokeneff proxy on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
