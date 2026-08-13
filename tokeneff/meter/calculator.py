"""Cost calculator: reads pricing_global.json to compute cost locally.

Reuses the billing logic from overseas/billing.py (load_pricing/get_model_pricing).
BYOK mode: charged = what the user actually pays upstream (official_input/output).
See design doc §3.5.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .types import CostBreakdown, UsageResult

PRICING_PATH = Path(__file__).parent.parent / "pricing" / "pricing_global.json"

# Fallback pricing for unknown models ($/M tokens) to avoid missed billing
_FALLBACK = {"input": 1.0, "output": 2.0}


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    with PRICING_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_model_pricing(model: str) -> dict | None:
    """Look up model pricing (Chinese models first, then international). Returns None if unknown."""
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
    """Compute the cost of a single request.

    BYOK mode: the user connects to upstream directly; charged = official price
    (what the user actually pays upstream), saved = 0.
    Platform mode: charged = our_* (our selling price), official = official price, saved > 0.
    """
    pricing = get_model_pricing(model)
    in_m = usage.input_tokens / 1_000_000
    out_m = usage.completion_tokens / 1_000_000

    if pricing is None:
        # Unknown model: use fallback price, official=charged
        charged = in_m * _FALLBACK["input"] + out_m * _FALLBACK["output"]
        return CostBreakdown(
            charged=round(charged, 6), official=round(charged, 6),
            saved=0.0, saved_pct=0.0,
            input_tokens=usage.input_tokens, output_tokens=usage.completion_tokens, model=model,
        )

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

    return CostBreakdown(
        charged=round(charged, 6),
        official=round(official, 6),
        saved=round(saved, 6),
        saved_pct=saved_pct,
        input_tokens=usage.input_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
    )
