"""Meter collector: aggregates usage + computes cost + writes to storage.

See design doc §3.4-supplement (Collector definition + M-NEW-2 currency passing).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from .. import config as cfg_module
from . import calculator
from .store import UsageStore
from .types import CostBreakdown, UsageRecord, UsageResult

# ★ H1 (audit): USD→CNY conversion rate for CN-region users. calculator returns USD
# (pricing.json is USD per M tokens); CNY users get real-¥ amounts at record time.
# TODO: make configurable (env/config) once FX fluctuation matters.
USD_CNY_RATE = 7.2


class Collector:
    """Meter data collector."""

    def __init__(self, store: Optional[UsageStore] = None):
        self.store = store or UsageStore()

    async def init(self):
        await self.store.init()

    async def close(self):
        await self.store.flush()
        await self.store.close()

    async def record(
        self,
        model: str,
        usage: UsageResult,
        cost: Optional[CostBreakdown] = None,
        elapsed: Optional[float] = None,
    ) -> None:
        """Final recording: compute cost and write to SQLite.

        cost may be None (compute locally in that case); currency is taken from config.get_currency().
        """
        if not usage.has_data:
            return
        if cost is None:
            mode = self._get_mode()
            cost = calculator.calculate(model, usage, mode)
        currency = self._get_currency()
        mode = self._get_mode()

        # ★ H1 fix (audit): calculator returns USD amounts (pricing.json is USD/M tokens).
        # For CNY users convert to real CNY at record time — previously the USD number was
        # stored with a "CNY" label, understating every amount by the FX rate (~7.2×).
        if currency == "CNY":
            rec = UsageRecord(
                timestamp=datetime.now().isoformat(timespec="seconds"),
                model=model,
                mode=mode,
                input_tokens=usage.input_tokens,
                output_tokens=usage.completion_tokens,
                charged_amount=round(cost.charged * USD_CNY_RATE, 6),
                official_amount=round(cost.official * USD_CNY_RATE, 6),
                saved_amount=round(cost.saved * USD_CNY_RATE, 6),
                currency=currency,
                latency_ms=int(elapsed * 1000) if elapsed else 0,
            )
        else:
            rec = UsageRecord(
                timestamp=datetime.now().isoformat(timespec="seconds"),
                model=model,
                mode=mode,
                input_tokens=usage.input_tokens,
                output_tokens=usage.completion_tokens,
                charged_amount=cost.charged,
                official_amount=cost.official,
                saved_amount=cost.saved,
                currency=currency,
                latency_ms=int(elapsed * 1000) if elapsed else 0,
            )
        await self.store.record(rec)
        # Persist immediately: metering is low-frequency (every record is a real cost), and
        # proxy(7860) and sidecar(7861) are separate processes sharing the same SQLite file —
        # the other side can only read data after it is written to the DB.
        # store.record buffers 50 records before flushing by default; across processes that
        # buffered data would be lost, so flush immediately here.
        await self.store.flush()

    @staticmethod
    def _get_currency() -> str:
        try:
            return cfg_module.get_config().get_currency()
        except Exception:
            return "USD"

    @staticmethod
    def _get_mode() -> str:
        try:
            return cfg_module.get_config().mode
        except Exception:
            return "byok"


# Global singleton
collector = Collector()
