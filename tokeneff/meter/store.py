"""本地 SQLite 用量存储。

关联设计文档 §3.7、§7.1（N3-M2 SQLite 并发优化）：
- 长连接 self._db 复用
- WAL 模式（读/写不互斥）
- busy_timeout 避免锁超时
- 批量写缓冲（满 50 条或定时 flush）
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite

from .types import UsageRecord

DB_PATH = Path.home() / ".tokeneff" / "meter.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    charged_amount REAL NOT NULL,
    official_amount REAL NOT NULL,
    saved_amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    latency_ms INTEGER,
    request_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_records(timestamp);
"""


class UsageStore:
    """本地 SQLite 用量存储（N3-M2 优化版）。"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None
        self._buffer: list[UsageRecord] = []
        self._flush_lock = asyncio.Lock()

    async def init(self):
        """初始化长连接 + WAL 模式。"""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self):
        """关闭长连接。"""
        if self._db:
            await self._db.close()
            self._db = None

    async def record(self, rec: UsageRecord):
        """写入缓冲，满 50 条或超 5 秒 flush 一次。"""
        self._buffer.append(rec)
        if len(self._buffer) >= 50:
            await self._flush()

    async def _flush(self):
        """批量写入。"""
        if not self._buffer or self._db is None:
            return
        async with self._flush_lock:
            batch, self._buffer = self._buffer, []
            await self._db.executemany(
                """INSERT INTO usage_records
                   (timestamp, model, mode, input_tokens, output_tokens,
                    charged_amount, official_amount, saved_amount, currency, latency_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(r.timestamp, r.model, r.mode,
                  r.input_tokens, r.output_tokens,
                  r.charged_amount, r.official_amount, r.saved_amount,
                  r.currency, r.latency_ms) for r in batch],
            )
            await self._db.commit()

    async def flush(self):
        """手动 flush（供外部调用）。"""
        await self._flush()

    # ── 读方法（WAL 模式读不互斥）───────────────────────────────────────

    async def get_today_total(self, currency: str = None) -> float:
        """今日总花费。可选按 currency 过滤（§3.6 避免 CNY/USD 混加）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        sql = "SELECT COALESCE(SUM(charged_amount), 0) FROM usage_records WHERE timestamp >= ?"
        params = [today]
        if currency:
            sql += " AND currency = ?"
            params.append(currency)
        async with self._db.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0

    async def get_month_total(self, currency: str = None) -> float:
        """本月累计花费。可选按 currency 过滤。"""
        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        sql = "SELECT COALESCE(SUM(charged_amount), 0) FROM usage_records WHERE timestamp >= ?"
        params = [month_start]
        if currency:
            sql += " AND currency = ?"
            params.append(currency)
        async with self._db.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0

    async def get_model_breakdown_today(self) -> list[dict]:
        """今日各模型花费分布。"""
        today = datetime.now().strftime("%Y-%m-%d")
        async with self._db.execute(
            """SELECT model, SUM(charged_amount) as cost, SUM(input_tokens+output_tokens) as tokens
               FROM usage_records WHERE timestamp >= ? GROUP BY model ORDER BY cost DESC""",
            (today,),
        ) as cur:
            rows = await cur.fetchall()
            return [{"model": r[0], "cost": r[1], "tokens": r[2]} for r in rows]

    async def get_recent_rate(self) -> float:
        """最近 7 天的日均花费。"""
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        async with self._db.execute(
            "SELECT COALESCE(SUM(charged_amount), 0) FROM usage_records WHERE timestamp >= ?",
            (week_ago,),
        ) as cur:
            row = await cur.fetchone()
            return (row[0] / 7) if row and row[0] else 0.0

    async def get_history_30d(self) -> list[UsageRecord]:
        """最近 30 天历史（供 predictor 用）。"""
        d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        async with self._db.execute(
            """SELECT timestamp, model, mode, input_tokens, output_tokens,
                      charged_amount, official_amount, saved_amount, currency, latency_ms
               FROM usage_records WHERE timestamp >= ? ORDER BY timestamp DESC""",
            (d30,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                UsageRecord(
                    timestamp=r[0], model=r[1], mode=r[2],
                    input_tokens=r[3], output_tokens=r[4],
                    charged_amount=r[5], official_amount=r[6],
                    saved_amount=r[7], currency=r[8], latency_ms=r[9] or 0,
                )
                for r in rows
            ]

    async def get_total_saved(self) -> float:
        """累计节省（official - charged）。"""
        async with self._db.execute(
            "SELECT COALESCE(SUM(saved_amount), 0) FROM usage_records",
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0

    async def clear(self):
        """清空所有用量数据。"""
        if self._db is None:
            return
        await self._db.execute("DELETE FROM usage_records")
        await self._db.commit()
