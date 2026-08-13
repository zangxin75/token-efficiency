"""calculator 定价计算测试。"""

from tokeneff.meter import calculator
from tokeneff.meter.types import UsageResult


def test_byok_charged_equals_official():
    """BYOK 模式：用户直连上游，charged = official，saved = 0。"""
    usage = UsageResult(input_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000)
    cost = calculator.calculate("deepseek-v4-flash", usage, "byok")
    assert cost.charged == cost.official
    assert cost.saved == 0.0
    assert cost.saved_pct == 0.0


def test_platform_charged_less_than_official_for_marked_up():
    """平台模式：加价模型 charged < official，saved > 0。"""
    usage = UsageResult(input_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
    # glm-5.2 在 pricing 里 our < official（包月批发）
    cost = calculator.calculate("glm-5.2", usage, "platform")
    if cost.official > cost.charged:
        assert cost.saved > 0
        assert 0 < cost.saved_pct <= 100


def test_unknown_model_fallback():
    """未知模型用兜底价，official=charged。"""
    usage = UsageResult(input_tokens=100_000, completion_tokens=100_000, total_tokens=200_000)
    cost = calculator.calculate("definitely-unknown-model-xyz", usage, "byok")
    assert cost.charged > 0
    assert cost.charged == cost.official  # 兜底时相等


def test_zero_usage():
    """零用量 → 零成本。"""
    usage = UsageResult(input_tokens=0, completion_tokens=0, total_tokens=0)
    cost = calculator.calculate("deepseek-v4-flash", usage, "byok")
    assert cost.charged == 0.0


def test_saved_pct_formula():
    """saved_pct 公式正确：(1 - charged/official)*100。"""
    usage = UsageResult(input_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
    cost = calculator.calculate("glm-5.2", usage, "platform")
    if cost.official > 0 and cost.charged < cost.official:
        expected = round((1 - cost.charged / cost.official) * 100, 1)
        assert cost.saved_pct == expected


def test_from_dict_extracts_openai_usage():
    """UsageResult.from_dict 从 OpenAI 格式响应提取 usage。"""
    payload = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    usage = UsageResult.from_dict(payload)
    assert usage.input_tokens == 100
    assert usage.completion_tokens == 50
    assert usage.has_data is True


def test_from_dict_empty_usage():
    """无 usage 字段 → empty。"""
    usage = UsageResult.from_dict({})
    assert usage.has_data is False
