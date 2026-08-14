"""UsageStore SQLite 测试。"""

import pytest

from tokeneff.meter.types import UsageRecord


@pytest.mark.asyncio
async def test_record_and_flush(tmp_db, sample_records):
    """写入 + flush + 读回。"""
    for rec in sample_records:
        await tmp_db.record(rec)
    await tmp_db.flush()
    today = await tmp_db.get_today_total()
    # deepseek 0.001+0.002 + gpt 0.01 = 0.013
    assert today == pytest.approx(0.013, abs=1e-6)


@pytest.mark.asyncio
async def test_model_breakdown(tmp_db, sample_records):
    """模型分布聚合（字段契约与前端 ModelBreakdown 对齐：charged/input_tokens/output_tokens）。"""
    for rec in sample_records:
        await tmp_db.record(rec)
    await tmp_db.flush()
    breakdown = await tmp_db.get_model_breakdown_today()
    models = {b["model"]: b for b in breakdown}
    assert "deepseek-v4-flash" in models
    assert "gpt-4o" in models
    assert models["deepseek-v4-flash"]["charged"] == pytest.approx(0.003, abs=1e-6)
    assert models["deepseek-v4-flash"]["input_tokens"] > 0
    assert models["deepseek-v4-flash"]["output_tokens"] > 0


@pytest.mark.asyncio
async def test_currency_field_persisted(tmp_db):
    """★ M-NEW-2: currency 字段正确写入。"""
    rec = UsageRecord("2026-08-12T10:00:00", "deepseek-v4-flash", "byok",
                      1000, 500, 0.001, 0.001, 0.0, "CNY", 100)
    await tmp_db.record(rec)
    await tmp_db.flush()
    history = await tmp_db.get_history_30d()
    assert len(history) == 1
    assert history[0].currency == "CNY"


@pytest.mark.asyncio
async def test_total_saved(tmp_db):
    """累计节省聚合。"""
    recs = [
        UsageRecord("2026-08-12T10:00:00", "glm-5.2", "platform",
                    1000, 500, 0.001, 0.002, 0.001, "USD", 100),
        UsageRecord("2026-08-12T11:00:00", "glm-5.2", "platform",
                    1000, 500, 0.001, 0.002, 0.001, "USD", 100),
    ]
    for rec in recs:
        await tmp_db.record(rec)
    await tmp_db.flush()
    saved = await tmp_db.get_total_saved()
    assert saved == pytest.approx(0.002, abs=1e-6)


@pytest.mark.asyncio
async def test_clear(tmp_db, sample_records):
    """清空数据。"""
    for rec in sample_records:
        await tmp_db.record(rec)
    await tmp_db.flush()
    await tmp_db.clear()
    assert await tmp_db.get_today_total() == 0.0


@pytest.mark.asyncio
async def test_empty_store_returns_zero(tmp_db):
    """空库返回 0 而非 None。"""
    assert await tmp_db.get_today_total() == 0.0
    assert await tmp_db.get_total_saved() == 0.0
    assert await tmp_db.get_model_breakdown_today() == []
