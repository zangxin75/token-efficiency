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
        # ★ M14 fix (audit): platform key not configured raises RuntimeError with a
        # helpful Chinese message — surface it as 400, not a bare 500.
        try:
            upstream_url, headers = platform_router.route(model, body, req_headers, path)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"error": str(e)}),
                status_code=400,
                media_type="application/json",
            )
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


def _scan_sse_usage_line(line: bytes, acc: dict) -> None:
    """Parse one SSE data line, accumulating usage from both wire formats.

    ★ M8 fix (audit): Anthropic streams scatter usage across events —
    message_start carries input_tokens, message_delta carries (cumulative)
    output_tokens. OpenAI streams put the final usage on the last chunk.
    max() accumulation handles both (deltas are cumulative, finals overwrite).
    """
    line = line.strip()
    if not line.startswith(b"data: "):
        return
    data_str = line[6:]
    if data_str.strip() == b"[DONE]":
        return
    try:
        data = json.loads(data_str)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    # OpenAI stream: top-level usage on the final chunk
    usage = data.get("usage")
    if isinstance(usage, dict):
        acc["in"] = max(acc["in"], usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        acc["out"] = max(acc["out"], usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    # Anthropic stream: message_start → message.usage.input_tokens
    if data.get("type") == "message_start":
        mu = (data.get("message") or {}).get("usage") or {}
        acc["in"] = max(acc["in"], mu.get("input_tokens") or 0)
    # Anthropic stream: message_delta → usage.output_tokens (cumulative)
    elif data.get("type") == "message_delta":
        du = data.get("usage") or {}
        acc["out"] = max(acc["out"], du.get("output_tokens") or 0)


async def _stream_and_meter(upstream_resp, model: str, mode: str, start_time: float):
    """流式响应：逐块透传 + 逐行 usage 采集（双格式）。

    ★ M8 fix: previously the whole stream was accumulated in memory and only the
    last OpenAI-format chunk was parsed — Anthropic streams (Claude Code, the
    highest-volume scenario) were never metered ($0 recorded). Now lines are
    parsed incrementally (no full-stream buffering) and both formats accumulate.
    """
    acc = {"in": 0, "out": 0}
    buffer = b""
    async for chunk in upstream_resp.aiter_raw():
        yield chunk
        # Parse complete lines as they arrive; keep only the trailing partial line
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            try:
                _scan_sse_usage_line(line, acc)
            except Exception:
                pass  # metering must never break the stream

    # Trailing partial line (stream ended without final newline)
    if buffer:
        try:
            _scan_sse_usage_line(buffer, acc)
        except Exception:
            pass

    # Record once at stream end
    elapsed = time.time() - start_time
    if acc["in"] or acc["out"]:
        usage = UsageResult(
            input_tokens=acc["in"],
            completion_tokens=acc["out"],
            total_tokens=acc["in"] + acc["out"],
            has_data=True,
        )
        try:
            await collector.record(model, usage, elapsed=elapsed)
            log.info(f"[metered stream] {model}: in={acc['in']} out={acc['out']}")
        except Exception as e:
            log.warning(f"stream usage record error: {e}")


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
