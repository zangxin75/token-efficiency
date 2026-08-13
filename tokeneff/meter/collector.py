"""电表采集器：聚合用量 + 计算成本 + 写入存储。

关联设计文档 §3.4-补（Collector 定义 + M-NEW-2 currency 传入）。
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


class Collector:
    """电表数据收集器。"""

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
        """最终记录：计算成本并写入 SQLite。

        cost 可为 None（此时本地算）；currency 从 config.get_currency() 取。
        """
        if not usage.has_data:
            return
        if cost is None:
            mode = self._get_mode()
            cost = calculator.calculate(model, usage, mode)
        currency = self._get_currency()
        mode = self._get_mode()
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
        # 即时落盘：电表是低频场景（每条都是真实花费），且 proxy(7860) 与
        # sidecar(7861) 是独立进程，共享同一 SQLite 文件——只有写库后对方才读得到。
        # store.record 默认攒 50 条才 flush，跨进程时缓冲数据会丢失，故此处立即 flush。
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


# 全局单例
collector = Collector()
