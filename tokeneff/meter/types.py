"""Meter core data types.

See design doc §3.4-supplement (N-M2 completion + M-NEW-1/M-NEW-2 field alignment).
Field names align with the store.py SQL schema: output_tokens (not completion_tokens), currency.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UsageResult:
    """Token usage parsed from the upstream response."""

    input_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    has_data: bool = True

    @staticmethod
    def from_dict(d: dict) -> "UsageResult":
        """Extract usage from an OpenAI- or Anthropic-format response body."""
        usage = {}
        if isinstance(d, dict):
            # OpenAI 格式: usage 在顶层; Anthropic 格式: message_start 事件的
            # usage 嵌套在 message 里（{"type":"message_start","message":{"usage":{...}}}）
            usage = d.get("usage") or d.get("message", {}).get("usage") or {}
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
    """Cost breakdown: charged (actually paid) / official (official price) / saved (savings)."""

    charged: float = 0.0
    official: float = 0.0
    saved: float = 0.0
    saved_pct: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@dataclass
class UsageRecord:
    """Complete record written to SQLite (field names align with the schema)."""

    timestamp: str  # ISO format
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
    """Month-end spend forecast result (§3.6)."""

    estimated: float = 0.0        # predicted total month-end spend
    current_spend: float = 0.0    # spend so far this month
    daily_avg: float = 0.0        # daily average this month
    confidence: float = 0.0       # confidence 0~1 (saturates after 7 days)
    currency: str = "USD"         # forecast currency
