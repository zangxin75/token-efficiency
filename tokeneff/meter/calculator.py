"""成本计算器：读 pricing_global.json 本地算成本。

复用 overseas/billing.py 的计费逻辑（load_pricing/get_model_pricing）。
BYOK 模式：charged = 用户向上游实付价（official_input/output）。
关联设计文档 §3.5。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .types import CostBreakdown, UsageResult

PRICING_PATH = Path(__file__).parent.parent / "pricing" / "pricing_global.json"

# 未知模型的兜底定价（$/M tokens），避免漏计费
_FALLBACK = {"input": 1.0, "output": 2.0}


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    with PRICING_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_model_pricing(model: str) -> dict | None:
    """查模型定价（中国模型优先，其次国际模型）。返回 None=未知。"""
    data = load_pricing()
    for key in ("models", "international_models"):
        entries = data.get(key, {})
        if model in entries:
            e = entries[model]
            return {
                "input": e.get("our_input", e.get("official_input", _FALLBACK["input"])),
                "output": e.get("our_output", e.get("official_output", _FALLBACK["output"])),
                "official_input": e.get("official_input", e.get("our_input", _FALLBACK["input"])),
                "official_output": e.get("official_output", e.get("our_output", _FALLBACK["output"])),
            }
    return None


def calculate(model: str, usage: UsageResult, mode: str = "byok") -> CostBreakdown:
    """计算单次请求成本。

    BYOK 模式：用户直连上游，charged = 官方原价（用户向上游实付），saved = 0。
    平台模式：charged = our_*（我们的售价），official = 官方原价，saved > 0。
    """
    pricing = get_model_pricing(model)
    in_m = usage.input_tokens / 1_000_000
    out_m = usage.completion_tokens / 1_000_000

    if pricing is None:
        # 未知模型：用兜底价，official=charged
        charged = in_m * _FALLBACK["input"] + out_m * _FALLBACK["output"]
        return CostBreakdown(
            charged=round(charged, 6), official=round(charged, 6),
            saved=0.0, saved_pct=0.0,
            input_tokens=usage.input_tokens, output_tokens=usage.completion_tokens, model=model,
        )

    official = in_m * pricing["official_input"] + out_m * pricing["official_output"]

    if mode == "byok":
        # BYOK：用户向上游实付 = 官方原价，无加价无节省
        charged = official
        saved = 0.0
    else:
        # 平台模式：charged = our_* 售价
        charged = in_m * pricing["input"] + out_m * pricing["output"]
        saved = official - charged

    saved_pct = round((1 - charged / official) * 100, 1) if official > 0 else 0.0

    return CostBreakdown(
        charged=round(charged, 6),
        official=round(official, 6),
        saved=round(saved, 6),
        saved_pct=saved_pct,
        input_tokens=usage.input_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
    )
