"""月终花费预测器（§3.6）。

基于历史趋势预测月终花费：混合预测 = 近期趋势(70%) + 线性外推(30%)。
按 currency 分组求和，避免 CNY + USD 混加。
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Optional

from ..config import get_config
from .store import UsageStore
from .types import MonthlyForecast, UsageRecord


class SpendPredictor:
    """基于历史趋势预测月终花费。"""

    def __init__(self, store: Optional[UsageStore] = None):
        self.store = store

    async def _get_store(self) -> UsageStore:
        if self.store is None:
            from ..meter.collector import collector
            self.store = collector.store
        return self.store

    def predict_monthly(self, history: list[UsageRecord], currency: str = "USD") -> MonthlyForecast:
        """预测月终花费（同步版本，供 TUI 调用）。

        Args:
            history: 历史记录列表
            currency: 目标币种（用于过滤）

        Returns:
            MonthlyForecast 预测结果
        """
        if not history:
            return MonthlyForecast(currency=currency)

        # 按 currency 过滤
        filtered = [r for r in history if r.currency == currency]
        if not filtered:
            return MonthlyForecast(currency=currency)

        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_elapsed = (now - month_start).days + 1
        days_in_month = calendar.monthrange(now.year, now.month)[1]

        # 本月累计花费（仅计算指定 currency）
        month_spend = sum(r.charged_amount for r in filtered if r.timestamp >= month_start.isoformat())

        if days_elapsed <= 0:
            return MonthlyForecast(
                estimated=0,
                current_spend=month_spend,
                daily_avg=0,
                confidence=0,
                currency=currency,
            )

        # 线性外推
        daily_avg = month_spend / days_elapsed if days_elapsed > 0 else 0
        linear_estimate = daily_avg * days_in_month

        # 加权移动平均（最近 7 天权重更高）
        recent_7d = [
            r for r in filtered
            if r.timestamp >= (now - timedelta(days=7)).isoformat()
        ]
        if recent_7d:
            recent_daily_avg = sum(r.charged_amount for r in recent_7d) / 7
        else:
            recent_daily_avg = daily_avg

        weighted_estimate = recent_daily_avg * days_in_month

        # 混合预测（近期趋势 70% + 线性 30%）
        estimated = weighted_estimate * 0.7 + linear_estimate * 0.3

        confidence = min(days_elapsed / 7, 1.0)  # 7 天后置信度拉满

        return MonthlyForecast(
            estimated=estimated,
            current_spend=month_spend,
            daily_avg=daily_avg,
            confidence=confidence,
            currency=currency,
        )

    async def predict_monthly_async(self, currency: Optional[str] = None) -> MonthlyForecast:
        """异步版本，供非 TUI 场景调用。"""
        store = await self._get_store()
        if currency is None:
            currency = get_config().get_currency()

        history = await store.get_history_30d()
        return self.predict_monthly(history, currency)


class BudgetAlert:
    """预算告警检查器。"""

    def __init__(self, threshold: float = 0.8):
        """
        Args:
            threshold: 告警阈值（默认 80%）
        """
        self.threshold = threshold

    async def check(self, store: UsageStore, budget: float) -> Optional[dict]:
        """检查是否触发预算告警。

        Returns:
            告警信息 dict 或 None（未触发）
        """
        if budget <= 0:
            return None

        currency = get_config().get_currency()
        month_spend = await store.get_month_total(currency=currency)
        pct = month_spend / budget

        if pct >= self.threshold:
            return {
                "triggered": True,
                "pct": pct,
                "month_spend": month_spend,
                "budget": budget,
                "currency": currency,
                "remaining": max(0, budget - month_spend),
            }

        return None
