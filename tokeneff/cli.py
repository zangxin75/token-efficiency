"""tokeneff CLI entry point.

Commands: setup (config wizard) / start (start proxy) / stats (meter) / config (view config).
"""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from . import config as cfg_module

console = Console()


@click.group()
@click.version_option(__version__, prog_name="tokeneff")
def main():
    """⚡ tokeneff — LLM API cost meter（本地 BYOK 代理 + 电表）。"""


@main.command()
def setup():
    """交互式配置向导（配 API key + 预算）。"""
    from .onboarding.wizard import run_setup_wizard
    run_setup_wizard()


@main.command()
@click.option("--host", default="127.0.0.1", help="监听地址")
@click.option("--port", default=None, type=int, help="监听端口（默认读配置 7860）")
def start(host, port):
    """启动本地 BYOK 代理。"""
    cfg = cfg_module.get_config()
    listen_port = port or cfg.proxy_port
    console.print(f"[bold cyan]⚡ 启动 tokeneff 代理[/bold cyan] → http://{host}:{listen_port}/v1")
    console.print(f"[dim]模式: {cfg.mode} | 地域: {cfg.region or '(未设置)'} | 货币: {cfg.get_currency()}[/dim]")
    console.print()
    from .proxy.server import run
    run(host=host, port=listen_port)


@main.command()
@click.option("--model", default=None, help="按模型名过滤")
def stats(model):
    """查看电表统计（今日花费/模型分布/省钱）。"""
    from .dashboard.stats import show_stats
    show_stats(model)


@main.command()
def dashboard():
    """实时电表 TUI（rich.Live 每 0.5s 刷新，Ctrl+C 退出）。"""
    from .dashboard.tui import run_dashboard
    run_dashboard()


@main.command(name="config")
def show_config():
    """查看当前配置。"""
    cfg = cfg_module.get_config()
    table = Table(title="tokeneff 配置", title_style="bold")
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("模式", cfg.mode)
    table.add_row("地域", cfg.region or "(未设置)")
    table.add_row("货币", cfg.get_currency())
    table.add_row("代理端口", str(cfg.proxy_port))
    table.add_row("月度预算", f"${cfg.budget_monthly_usd}")
    table.add_row("配置文件", str(cfg_module.CONFIG_PATH))

    # Configured keys (plaintext not shown)
    from .proxy.model_registry import PROVIDER_REGISTRY
    configured = [p for p in PROVIDER_REGISTRY if cfg_module.get_api_key(p)]
    table.add_row("已配 key 的 provider", ", ".join(configured) or "(无)")
    console.print(table)


if __name__ == "__main__":
    main()
