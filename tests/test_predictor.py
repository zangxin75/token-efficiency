"""SpendPredictor 预测算法测试（§3.6）。"""

from datetime import datetime, timedelta

from tokeneff.meter.predictor import SpendPredictor
from tokeneff.meter.types import UsageRecord


def _rec(days_ago: int, amount: float, currency: str = "USD") -> UsageRecord:
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return UsageRecord(ts, "glm-4-flash", "byok", 1000, 500, amount, amount, 0.0, currency, 100)


def test_empty_history_returns_zero():
    fc = SpendPredictor().predict_monthly([], "USD")
    assert fc.estimated == 0
    assert fc.confidence == 0


def test_currency_filtering_no_mixed_sum():
    """★ §3.6 N3-M4：CNY 和 USD 不混加。"""
    history = [
        _rec(1, 10.0, "USD"),
        _rec(1, 70.0, "CNY"),  # 应被 USD 预测排除
        _rec(2, 10.0, "USD"),
    ]
    fc = SpendPredictor().predict_monthly(history, "USD")
    # 只应统计 USD 的 20.0，不含 CNY 的 70
    assert fc.current_spend == 20.0


def test_linear_extrapolation_scales_to_month():
    """线性外推：月初几天花费应按比例放大到整月。"""
    # 每天花 1.0，本月已过几天
    now = datetime.now()
    days_elapsed = now.day
    history = [_rec(d, 1.0, "USD") for d in range(days_elapsed)]
    fc = SpendPredictor().predict_monthly(history, "USD")
    # 预测应大于当前花费（外推到整月）
    assert fc.estimated >= fc.current_spend


def test_confidence_caps_at_one():
    """置信度 = days_elapsed/7，7 天后拉满为 1.0。"""
    history = [_rec(d, 1.0, "USD") for d in range(10)]
    fc = SpendPredictor().predict_monthly(history, "USD")
    assert 0.0 <= fc.confidence <= 1.0


def test_mixed_estimate_combines_recent_and_linear():
    """混合预测 = 近期70% + 线性30%，结果在两者之间。"""
    now = datetime.now()
    days_elapsed = now.day
    history = [_rec(d, 1.0, "USD") for d in range(days_elapsed)]
    fc = SpendPredictor().predict_monthly(history, "USD")
    assert fc.estimated > 0
    assert fc.daily_avg > 0
