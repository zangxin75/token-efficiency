"""Cost calculator: reads pricing_global.json to compute cost locally.

Reuses the billing logic from overseas/billing.py (load_pricing/get_model_pricing).
BYOK mode: charged = what the user actually pays upstream (official_input/output).
See design doc §3.5.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("tokeneff.calculator")

from .types import CostBreakdown, UsageResult

PRICING_PATH = Path(__file__).parent.parent / "pricing" / "pricing_global.json"

# Fallback pricing for unknown models ($/M tokens) to avoid missed billing
_FALLBACK = {"input": 1.0, "output": 2.0}

# USD → CNY conversion rate (display/record-level conversion; pricing_global.json
# is USD-only). Mirrors onboarding/wizard.py's budget conversion. Update when the
# gateway publishes a native CNY pricing table.
USD_TO_CNY = 7.2


@lru_cache(maxsize=1)
def _load_pricing_cached() -> dict:
    """Load the pricing table; raise on failure so lru_cache never stores it.

    lru_cache 只缓存正常 return 的值，不缓存异常 -- 失败在这里直接抛出，
    下次调用会重试读盘（目录恢复后自愈）。
    """
    with PRICING_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_pricing() -> dict:
    """Load the pricing table, falling back to an empty table on failure.

    * PyInstaller onefile 修复：资源解压在临时 _MEIxxxxx 目录，进程被强杀
    （taskkill /F）后残留清理可能删掉在跑实例的解压目录 -- 此后每次 meter
    读价格表都 FileNotFoundError，计量静默丢失（只留 warning 日志）。失败时
    回退空表（get_model_pricing 再落 _FALLBACK），保证计量永不因价格表缺失
    而丢记录；同时失败不进缓存，目录恢复后可自愈。
    """
    try:
        return _load_pricing_cached()
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"pricing table unavailable ({e}); using fallback pricing")
        return {"models": {}, "international_models": {}}


load_pricing.cache_clear = _load_pricing_cached.cache_clear  # type: ignore[attr-defined]


def get_model_pricing(model: str) -> dict | None:
    """Look up model pricing (Chinese models first, then international).

    Returns None if unknown - calculate() then falls back to _FALLBACK rates
    (定价表缺失时保证计量不丢，费率按兜底估算)。
    """
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


def calculate(
    model: str, usage: UsageResult, mode: str = "byok", currency: str = "USD"
) -> CostBreakdown:
    """Compute the cost of a single request.

    BYOK mode: the user connects to upstream directly; charged = official price
    (what the user actually pays upstream), saved = 0.
    Platform mode: charged = our_* (our selling price), official = official price, saved > 0.

    currency: pricing_global.json is USD-only; when currency="CNY" the result is
    converted at the record level (* review fix - previously USD numbers were
    stored with a CNY label, inflating/mislabeling readings by ~7x).
    """
    pricing = get_model_pricing(model)
    in_m = usage.input_tokens / 1_000_000
    out_m = usage.completion_tokens / 1_000_000

    if pricing is None:
        # Unknown model: use fallback price, official=charged.
        # * review fix: warn - fallback-priced records silently inflate the meter
        # (users see a higher number with no way to tell why); pricing table
        # updates are the actual fix, this makes the gap visible.
        log.warning(
            "no pricing entry for model '%s'; billed at fallback $%.1f/$%.1f per M tokens (estimate)",
            model, _FALLBACK["input"], _FALLBACK["output"],
        )
        charged = in_m * _FALLBACK["input"] + out_m * _FALLBACK["output"]
        official = charged
        saved = 0.0
        saved_pct = 0.0
    else:
        official = in_m * pricing["official_input"] + out_m * pricing["official_output"]

        if mode == "byok":
            # BYOK: what the user pays upstream = official price; no markup, no savings
            charged = official
            saved = 0.0
        else:
            # Platform mode: charged = our_* selling price
            charged = in_m * pricing["input"] + out_m * pricing["output"]
            saved = official - charged

        saved_pct = round((1 - charged / official) * 100, 1) if official > 0 else 0.0

    if currency == "CNY":
        charged *= USD_TO_CNY
        official *= USD_TO_CNY
        saved *= USD_TO_CNY

    return CostBreakdown(
        charged=round(charged, 6),
        official=round(official, 6),
        saved=round(saved, 6),
        saved_pct=saved_pct,
        input_tokens=usage.input_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
    )
