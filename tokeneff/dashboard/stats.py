"""Meter stats display: outputs spend / model breakdown / savings attribution via rich tables.

MVP uses command-line tables (not Live TUI; TUI deferred to v0.1 enhancement).
See design doc §6.2, §15.
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.table import Table

from .. import config as cfg_module
from ..meter.format import format_money
from ..meter.predictor import BudgetAlert, SpendPredictor
from ..meter.store import UsageStore

console = Console()


def _char_bar(pct: float, width: int = 24) -> str:
    """Character progress bar (rich.bar.Bar does not exist; §6.3 M5 revision)."""
    pct = max(0.0, min(pct, 100.0))
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if pct < 60 else ("yellow" if pct < 80 else "red")
    return f"[{color}]{bar}[/{color}] {pct:.0f}%"


async def _gather_stats(store: UsageStore, currency: str) -> dict:
    today = await store.get_today_total(currency=currency)
    month = await store.get_month_total(currency=currency)
    models = await store.get_model_breakdown_today()
    rate = await store.get_recent_rate()
    saved = await store.get_total_saved()
    history = await store.get_history_30d()
    forecast = SpendPredictor().predict_monthly(history, currency)
    return {
        "today": today, "month": month, "models": models,
        "rate": rate, "saved": saved, "forecast": forecast,
    }


def show_stats(model_filter: str | None = None) -> None:
    """Display meter stats."""
    cfg = cfg_module.get_config()
    currency = cfg.get_currency()

    async def _run():
        store = UsageStore()
        await store.init()
        try:
            stats = await _gather_stats(store, currency)
        finally:
            await store.flush()
            await store.close()
        return stats

    stats = asyncio.run(_run())

    # Title
    console.print()
    console.print(f"[bold cyan]⚡ tokeneff 电表[/bold cyan]  [dim]({currency})[/dim]")
    console.print()

    # Overview
    overview = Table(show_header=False, box=None, padding=(0, 2))
    overview.add_row("今日花费", format_money(stats['today'], currency))
    overview.add_row("本月累计", format_money(stats['month'], currency))
    overview.add_row("近 7 天日均", format_money(stats['rate'], currency))

    # ★ v0.2: month-end forecast
    fc = stats["forecast"]
    if fc.confidence > 0.1:
        overview.add_row(
            "月终预测",
            f"~{format_money(fc.estimated, currency)} [dim]({fc.confidence:.0%} 置信)[/dim]",
        )

    overview.add_row("累计节省", f"[green]{format_money(stats['saved'], currency)}[/green]")
    console.print(overview)
    console.print()

    # ★ v0.2: budget alert (show progress bar + threshold alert when monthly budget > 0)
    budget = cfg_module.get_config().get_budget_in()
    if budget > 0:
        pct = stats["month"] / budget * 100
        console.print(
            f"预算进度  {format_money(stats['month'], currency)} / {format_money(budget, currency)}  " + _char_bar(pct)
        )
        if pct >= 80:
            console.print(
                f"[bold red]⚠ 已用 {pct:.0f}%，超过 80% 告警阈值，请注意控制用量[/bold red]"
            )
        console.print()

    # Model breakdown
    models = stats["models"]
    if model_filter:
        models = [m for m in models if model_filter.lower() in m["model"].lower()]

    if models:
        table = Table(title="今日模型花费分布", title_style="bold")
        table.add_column("模型", style="cyan")
        table.add_column("花费", justify="right")
        table.add_column("tokens", justify="right")
        for m in models:
            table.add_row(m["model"], format_money(m["cost"], currency), f"{m['tokens']:,}")
        console.print(table)
    else:
        console.print("[dim]暂无今日用量数据[/dim]")
    console.print()
