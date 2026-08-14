"""Month-end spend forecaster (§3.6).

Forecasts month-end spend based on historical trends:
hybrid forecast = recent trend (70%) + linear extrapolation (30%).
Summed per currency to avoid mixing CNY + USD.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Optional

from ..config import get_config
from .store import UsageStore
from .types import MonthlyForecast, UsageRecord


class SpendPredictor:
    """Forecast month-end spend based on historical trends."""

    def __init__(self, store: Optional[UsageStore] = None):
        self.store = store

    async def _get_store(self) -> UsageStore:
        if self.store is None:
            from ..meter.collector import collector
            self.store = collector.store
        return self.store

    def predict_monthly(self, history: list[UsageRecord], currency: str = "USD") -> MonthlyForecast:
        """Forecast month-end spend (sync version, for TUI use).

        Args:
            history: list of historical records
            currency: target currency (used for filtering)

        Returns:
            MonthlyForecast forecast result
        """
        if not history:
            return MonthlyForecast(currency=currency)

        # Filter by currency
        filtered = [r for r in history if r.currency == currency]
        if not filtered:
            return MonthlyForecast(currency=currency)

        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_elapsed = (now - month_start).days + 1
        days_in_month = calendar.monthrange(now.year, now.month)[1]

        # Month-to-date spend (only the specified currency)
        month_spend = sum(r.charged_amount for r in filtered if r.timestamp >= month_start.isoformat())

        if days_elapsed <= 0:
            return MonthlyForecast(
                estimated=0,
                current_spend=month_spend,
                daily_avg=0,
                confidence=0,
                currency=currency,
            )

        # Linear extrapolation
        daily_avg = month_spend / days_elapsed if days_elapsed > 0 else 0
        linear_estimate = daily_avg * days_in_month

        # Weighted moving average (more recent 7 days get higher weight)
        recent_7d = [
            r for r in filtered
            if r.timestamp >= (now - timedelta(days=7)).isoformat()
        ]
        if recent_7d:
            recent_daily_avg = sum(r.charged_amount for r in recent_7d) / 7
        else:
            recent_daily_avg = daily_avg

        weighted_estimate = recent_daily_avg * days_in_month

        # Hybrid forecast (recent trend 70% + linear 30%)
        estimated = weighted_estimate * 0.7 + linear_estimate * 0.3

        confidence = min(days_elapsed / 7, 1.0)  # confidence saturates after 7 days

        return MonthlyForecast(
            estimated=estimated,
            current_spend=month_spend,
            daily_avg=daily_avg,
            confidence=confidence,
            currency=currency,
        )

    async def predict_monthly_async(self, currency: Optional[str] = None) -> MonthlyForecast:
        """Async version, for non-TUI scenarios."""
        store = await self._get_store()
        if currency is None:
            currency = get_config().get_currency()

        history = await store.get_history_30d()
        return self.predict_monthly(history, currency)


class BudgetAlert:
    """Budget alert checker."""

    def __init__(self, threshold: float = 80.0):
        """
        Args:
            threshold: alert threshold in percent (default 80%)
        """
        self.threshold = threshold

    async def check(self, store: UsageStore, budget: float) -> Optional[dict]:
        """Check whether a budget alert should be triggered.

        Returns:
            alert info dict, or None (not triggered)
        """
        if budget <= 0:
            return None

        currency = get_config().get_currency()
        # ★ review fix: budget 参数语义为 USD（与 budget_monthly_usd 存储一致），
        # month_spend 却是区域币种（cn→CNY）——先换算再比较，否则百分比膨胀 7.2 倍
        if currency == "CNY":
            from ..meter.calculator import USD_TO_CNY
            budget = budget * USD_TO_CNY
        month_spend = await store.get_month_total(currency=currency)
        pct = month_spend / budget if budget > 0 else 0

        # threshold is percent (10-100); pct is 0-1 — compare in the same scale
        if pct * 100 >= self.threshold:
            return {
                "triggered": True,
                "pct": pct,
                "month_spend": month_spend,
                "budget": budget,
                "currency": currency,
                "remaining": max(0, budget - month_spend),
            }

        return None
