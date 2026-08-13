"""金额格式化工具。

★ B3 回流修复：单次 LLM 请求常是几厘钱（如 $0.000077），
:.4f 会截成 $0.0000 不可见。智能格式化：小额多显示位数，大额少显示。
"""

from __future__ import annotations


def format_money(amount: float, currency: str = "USD") -> str:
    """智能金额格式化。

    - 0 → "0.00"
    - < 0.01 → 科学计数般保留 6 位有效（如 0.000077 → "0.000077"）
    - 0.01 ~ 1 → 4 位（"0.0123"）
    - ≥ 1 → 2 位（"3.45"）

    带 currency 符号前缀（CNY→¥，USD→$）。
    """
    symbol = "¥" if currency == "CNY" else "$"
    if amount == 0:
        return f"{symbol}0.00"
    abs_amt = abs(amount)
    if abs_amt < 0.01:
        # 小额：保留 6 位小数，去掉末尾多余的 0
        return f"{symbol}{amount:.6f}".rstrip("0").rstrip(".")
    if abs_amt < 1:
        return f"{symbol}{amount:.4f}"
    return f"{symbol}{amount:.2f}"
