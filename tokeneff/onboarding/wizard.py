"""配置向导：交互式引导用户配置 BYOK key。

关联设计文档 §5.3（run_setup_wizard 同步版）+ H-NEW-5（async 调用链）。
MVP 简化版：检测 region → 选 provider → 配 key → verify → 存 keyring。
完整中国模型申请引导留待 v0.2。
"""

from __future__ import annotations

import asyncio

import questionary
from rich.console import Console

from .. import config as cfg_module
from ..proxy import byok_router
from ..proxy.model_registry import PROVIDER_REGISTRY
from ..region import detect_region

console = Console()


def run_setup_wizard() -> None:
    """交互式配置向导（同步）。"""
    console.print()
    console.print("[bold cyan]⚡ tokeneff 配置向导[/bold cyan]")
    console.print("[dim]BYOK 模式：你自带 API key，tokeneff 只做本地计费，key 不离开本机[/dim]")
    console.print()

    cfg = cfg_module.get_config()

    # Step 1: 地域（自动检测 + 确认）
    detected = detect_region()
    region = questionary.select(
        "你的地域？（影响定价货币 ¥/$）",
        choices=["cn", "global"],
        default=detected,
    ).ask()
    cfg.region = region

    # Step 2: 选 provider 配 key
    console.print()
    providers = list(PROVIDER_REGISTRY.keys())
    chosen = questionary.checkbox(
        "选择你要使用的 API provider（空格选择，可多选）：",
        choices=providers,
    ).ask()

    for provider in chosen or []:
        info = PROVIDER_REGISTRY[provider]
        console.print(f"\n[cyan]{provider}[/cyan] — 注册地址: {info.get('register_url', 'N/A')}")
        key = questionary.password(f"粘贴你的 {provider} API key:").ask()
        if not key:
            console.print("[dim]跳过[/dim]")
            continue

        # verify（async，同步向导里用 asyncio.run）
        console.print(f"[dim]验证 {provider} key...[/dim]")
        ok, msg = asyncio.run(byok_router.verify_key(provider, key))
        console.print(f"  {msg}")
        if ok:
            cfg_module.set_api_key(provider, key)
            console.print(f"  [green]✓ {provider} key 已保存到 keyring[/green]")
        else:
            still = questionary.confirm("key 验证失败，仍要保存吗？").ask()
            if still:
                cfg_module.set_api_key(provider, key)

    # Step 3: 预算（可选）
    console.print()
    budget = questionary.text(
        f"月度预算（{cfg.get_currency()}，0=不限）：",
        default="0",
    ).ask()
    try:
        budget_val = float(budget or 0)
        if cfg.region == "cn":
            # CN 预算统一存 USD（¥÷汇率）
            cfg.budget_monthly_usd = round(budget_val / 7.2, 4)
        else:
            cfg.budget_monthly_usd = budget_val
    except ValueError:
        pass

    # Step 4: 保存
    cfg_module.save(cfg)
    console.print()
    console.print("[bold green]✅ 配置完成！[/bold green]")
    console.print(f"  配置文件: {cfg_module.CONFIG_PATH}")
    console.print(f"  现在运行 [cyan]tokeneff start[/cyan] 启动本地代理 (localhost:{cfg.proxy_port})")
    console.print(f"  然后把客户端的 base_url 指向 [cyan]http://localhost:{cfg.proxy_port}/v1[/cyan]")
