"""电表核心数据类型。

关联设计文档 §3.4-补（N-M2 补全 + M-NEW-1/M-NEW-2 字段对齐）。
字段名与 store.py 的 SQL schema 对齐：output_tokens（非 completion_tokens）、currency。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UsageResult:
    """从上游响应解析出的 token 用量。"""

    input_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    has_data: bool = True

    @staticmethod
    def from_dict(d: dict) -> "UsageResult":
        """从 OpenAI 格式响应体提取 usage。"""
        usage = d.get("usage", {}) if isinstance(d, dict) else {}
        if not usage:
            return UsageResult.empty()
        return UsageResult(
            input_tokens=usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0) or usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            has_data=True,
        )

    @staticmethod
    def empty() -> "UsageResult":
        return UsageResult(0, 0, 0, has_data=False)


@dataclass
class CostBreakdown:
    """成本分解：charged（实收）/ official（官方原价）/ saved（节省）。"""

    charged: float = 0.0
    official: float = 0.0
    saved: float = 0.0
    saved_pct: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@dataclass
class UsageRecord:
    """写入 SQLite 的完整记录（字段名与 schema 对齐）。"""

    timestamp: str  # ISO 格式
    model: str
    mode: str  # "byok" | "platform"
    input_tokens: int
    output_tokens: int
    charged_amount: float
    official_amount: float
    saved_amount: float
    currency: str = "USD"  # ★ M-NEW-2: CNY/USD
    latency_ms: int = 0


@dataclass
class MonthlyForecast:
    """月终花费预测结果（§3.6）。"""

    estimated: float = 0.0        # 预测月终总花费
    current_spend: float = 0.0    # 本月已花费
    daily_avg: float = 0.0        # 本月日均
    confidence: float = 0.0       # 置信度 0~1（7 天后拉满）
    currency: str = "USD"         # 预测币种
