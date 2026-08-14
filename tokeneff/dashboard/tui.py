"""Real-time meter TUI (§6.3): refreshes in real time via rich.Live.

Four-block layout: summary (today/month/month-end forecast), by_model (distribution),
savings (savings attribution), live_rate (real-time rate).

Note: store methods are async — the design-doc examples wrote them as sync. This
implementation is uniformly async; render() awaits to collect a data snapshot before returning.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import config as cfg_module
from ..meter.format import format_money
from ..meter.predictor import SpendPredictor
from ..meter.store import UsageStore


class MeterDashboard:
    """Meter terminal UI, refreshed in real time via rich.Live."""

    def __init__(self, store: UsageStore):
        self.store = store
        self.predictor = SpendPredictor(store)
        self.refresh_interval = 0.5  # 500ms
        self.currency = cfg_module.get_config().get_currency()

    async def render(self) -> Layout:
        """Render the full dashboard layout (collects an async data snapshot first)."""
        today = await self.store.get_today_total(currency=self.currency)
        month = await self.store.get_month_total(currency=self.currency)
        breakdown = await self.store.get_model_breakdown_today()
        saved = await self.store.get_total_saved()
        rate = await self.store.get_recent_rate()
        history = await self.store.get_history_30d()
        forecast = self.predictor.predict_monthly(history, self.currency)
        budget = cfg_module.get_config().get_budget_in()

        layout = Layout()
        layout.split_column(
            Layout(self._render_summary(today, month, forecast, budget), name="summary", size=7),
            Layout(self._render_by_model(breakdown), name="by_model", size=12),
            Layout(self._render_savings(saved), name="savings", size=5),
            Layout(self._render_live_rate(rate), name="rate", size=4),
        )
        return layout

    def _render_summary(self, today, month, forecast, budget) -> Panel:
        """Top: today / month / month-end forecast."""
        table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
        table.add_column("label", style="dim", width=14)
        table.add_column("value", style="bold", width=16)
        table.add_column("bar", width=34)

        max_val = max(today, month / 30, 0.0001)
        table.add_row("今日 Today", format_money(today, self.currency), self._mini_bar(today, max_val * 8))

        month_pct = (month / budget * 100) if budget > 0 else 0
        bar = self._char_bar_color(month_pct, 28) if budget > 0 else ""
        table.add_row("本月 Month", format_money(month, self.currency), bar)

        if forecast.confidence > 0.1:
            table.add_row(
                "月终预测 Est.",
                f"~{format_money(forecast.estimated, self.currency)}",
                Text(f"{forecast.confidence:.0%} 置信", style="dim"),
            )

        return Panel(table, title="⚡ TokenEff 电表", border_style="cyan")

    def _render_by_model(self, breakdown) -> Panel:
        """Middle: cost breakdown per model."""
        table = Table(box=None, padding=(0, 1), expand=True)
        table.add_column("模型", style="cyan", width=22)
        table.add_column("花费", justify="right", width=12)
        table.add_column("tokens", justify="right", width=14)
        table.add_column("占比", width=22)

        max_cost = max((b["cost"] for b in breakdown), default=1)
        for b in breakdown[:8]:
            pct = b["cost"] / max_cost if max_cost > 0 else 0
            table.add_row(
                b["model"],
                format_money(b['cost'], self.currency),
                f"{b['tokens']:,}",
                self._char_bar(pct * 100, 18),
            )

        if not breakdown:
            table.add_row("[dim]暂无数据[/dim]", "", "", "")

        return Panel(table, title="今日模型分布", border_style="blue")

    def _render_savings(self, saved) -> Panel:
        """Savings attribution."""
        text = Text()
        text.append("💰 vs 官方定价累计节省  ", style="dim")
        text.append(format_money(saved, self.currency), style="bold green")
        return Panel(text, border_style="green")

    def _render_live_rate(self, rate) -> Panel:
        """Bottom: real-time rate (tokens/min)."""
        text = Text()
        if rate > 0:
            text.append("⚡ ", style="yellow")
            text.append(f"{format_money(rate, self.currency)}/min", style="bold")
            text.append(f"  ·  更新于 {datetime.now().strftime('%H:%M:%S')}", style="dim")
        else:
            text.append("⚪ Idle — 等待请求...", style="dim")
        return Panel(text, border_style="dim")

    def _mini_bar(self, value: float, max_val: float) -> str:
        """Mini progress bar characters."""
        if max_val <= 0:
            return ""
        bars = "▁▂▃▄▅▆▇█"
        idx = min(int(value / max_val * 7), 7)
        return bars[idx]

    def _char_bar(self, pct: float, width: int = 20) -> str:
        """Character progress bar (§6.3 M5: replaces the nonexistent rich.bar.Bar)."""
        filled = min(int(pct / 100 * width), width)
        return "[green]" + "█" * filled + "[/green]" + "░" * (width - filled)

    def _char_bar_color(self, pct: float, width: int = 28) -> str:
        """Progress bar with color thresholds (green<60, yellow<80, red>=80)."""
        pct = max(0.0, min(pct, 100.0))
        filled = min(int(pct / 100 * width), width)
        color = "green" if pct < 60 else ("yellow" if pct < 80 else "red")
        return f"[{color}]" + "█" * filled + f"[/{color}]" + "░" * (width - filled) + f" {pct:.0f}%"

    async def run(self):
        """Start the real-time refresh loop."""
        await self.store.init()
        try:
            with Live(await self.render(), refresh_per_second=2, screen=True) as live:
                while True:
                    await asyncio.sleep(self.refresh_interval)
                    live.update(await self.render())
        finally:
            await self.store.flush()
            await self.store.close()


def run_dashboard() -> None:
    """CLI entry point: start the real-time meter."""
    store = UsageStore()
    dash = MeterDashboard(store)
    try:
        asyncio.run(dash.run())
    except KeyboardInterrupt:
        pass
