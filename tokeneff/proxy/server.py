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


def _is_native_anthropic(body: dict) -> bool:
    """判断请求是否已是 Anthropic 原生格式（如 Claude Code 发的）。

    信号：messages 里无 system role（Anthropic 把 system 放顶层）且带 max_tokens。
    OpenAI SDK 客户端会把 system 作为 message 发，需 adapt；原生客户端已是目标格式，
    adapt 反而会丢弃 tools/system 等字段，故对原生请求短路跳过。
    """
    messages = body.get("messages", [])
    has_system_role = any(m.get("role") == "system" for m in messages)
    return not has_system_role and "max_tokens" in body


# ═══════════════════════════════════════════════════════════════════════════════
# 拦截入口
# ═══════════════════════════════════════════════════════════════════════════════


@app.api_route("/{path:path}", methods=["POST"])
async def intercept(request: Request, path: str):
    """拦截所有 POST 请求（/v1/chat/completions 等）。

    流程：route → adapt(anthropic) → 上游 → 计费 → 返回。
    """
    # ★ H2 fix (audit): require a non-empty Authorization header.
    # Blocks browser no-cors drive-by billing: a text/plain POST is a CORS "simple request"
    # that skips preflight, so any malicious webpage could otherwise silently burn the
    # user's keyring-stored key. Legitimate SDK clients always send an Authorization
    # header (OpenAI SDK requires api_key; Claude Code sends auth); no-cors form posts
    # cannot attach custom headers.
    auth = request.headers.get("authorization", "").strip()
    if not auth:
        return Response(
            content=json.dumps({"error": "missing Authorization header"}),
            status_code=401,
            media_type="application/json",
        )

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
    # BYOK 模式下需保护 Anthropic 原生客户端（Claude Code），adapt 会丢弃其 tools/system。
    if provider_format == "anthropic" and not _is_native_anthropic(body_json):
        body = byok_router.adapt_request_body(body, provider_format)

    is_stream = _is_stream_request(body_json)

    # 4. 转发到上游
    start_time = time.time()

    # 5. 处理响应：非流式 vs 流式
    if is_stream:
        # ★ 流式：httpx client 必须存活到流消费完毕。把 client 创建、send、
        # 逐块 yield 合并进同一生成器，让 with 在流结束后才退出，
        # 否则 client 提前关闭导致 aiter_raw() 抛 httpx.ReadError / ECONNRESET。
        return StreamingResponse(
            _stream_proxy(upstream_url, body, headers, model, mode, start_time),
            media_type="text/event-stream",
        )

    # 非流式：独立 client，全量读完后即可释放
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            upstream_resp = await client.post(upstream_url, content=body, headers=headers)
        except Exception as e:
            log.error(f"upstream error: {e}")
            return Response(content=f"Upstream error: {e}", status_code=502)

        content = upstream_resp.content
        elapsed = time.time() - start_time

        if upstream_resp.status_code != 200:
            return Response(
                content=content,
                status_code=upstream_resp.status_code,
                headers={"content-type": upstream_resp.headers.get("content-type", "application/json")},
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
            headers={"content-type": upstream_resp.headers.get("content-type", "application/json")},
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


async def _stream_proxy(upstream_url, body, headers, model, mode, start_time):
    """★ 流式转发：在生成器内管理 httpx client 生命周期。

    client.send(stream=True) 返回的响应必须在其 client 存活期间消费，
    故 client 创建与流消费必须同处一个 async with——generator 不结束，with 不退出。
    非流式分支因 aread() 同步完成无此约束。
    """
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            async with client.stream("POST", upstream_url, content=body, headers=headers) as upstream_resp:
                async for chunk in _stream_and_meter(upstream_resp, model, mode, start_time):
                    yield chunk
        except Exception as e:
            log.error(f"stream proxy error: {e}")
            raise


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
