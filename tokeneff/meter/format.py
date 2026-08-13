"""Money formatting utility.

★ B3 regression fix: a single LLM request often costs a fraction of a cent
(e.g. $0.000077); :.4f would truncate it to the invisible $0.0000.
Smart formatting: show more digits for small amounts, fewer for large ones.
"""

from __future__ import annotations


def format_money(amount: float, currency: str = "USD") -> str:
    """Smart money formatting.

    - 0 → "0.00"
    - < 0.01 → keep 6 significant digits like scientific notation (e.g. 0.000077 → "0.000077")
    - 0.01 ~ 1 → 4 digits ("0.0123")
    - ≥ 1 → 2 digits ("3.45")

    Prefixed with the currency symbol (CNY→¥, USD→$).
    """
    symbol = "¥" if currency == "CNY" else "$"
    if amount == 0:
        return f"{symbol}0.00"
    abs_amt = abs(amount)
    if abs_amt < 0.01:
        # Small amount: keep 6 decimal places, strip trailing zeros
        return f"{symbol}{amount:.6f}".rstrip("0").rstrip(".")
    if abs_amt < 1:
        return f"{symbol}{amount:.4f}"
    return f"{symbol}{amount:.2f}"
