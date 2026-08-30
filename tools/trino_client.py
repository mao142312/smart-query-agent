from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any


class SQLiteDemoClient:
    """Deterministic local query engine mirroring the tables used by generated SQL."""

    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self._seed()

    def _seed(self) -> None:
        cur = self.connection.cursor()
        cur.executescript("""
            CREATE TABLE account_openings (
              user_id TEXT, region TEXT, opened_at TEXT, status TEXT
            );
            CREATE TABLE transactions (
              transaction_id TEXT, user_id TEXT, region TEXT,
              amount REAL, traded_at TEXT, status TEXT
            );
        """)
        today = date.today()
        openings = []
        transactions = []
        regions = ["香港", "上海", "北京"]
        for days_ago in range(0, 15):
            day = (today - timedelta(days=days_ago)).isoformat()
            for region_index, region in enumerate(regions):
                count = 2 + ((days_ago + region_index) % 4)
                for index in range(count):
                    openings.append((f"u-{days_ago}-{region_index}-{index}", region, day, "SUCCESS"))
                    transactions.append((f"t-{days_ago}-{region_index}-{index}", f"u-{index}", region,
                                         float((index + 1) * 100), day, "SUCCESS"))
        cur.executemany("INSERT INTO account_openings VALUES (?, ?, ?, ?)", openings)
        cur.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)", transactions)
        self.connection.commit()

    def execute(self, sql: str) -> list[dict[str, Any]]:
        cursor = self.connection.execute(sql)
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self.connection.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class TrinoClient:
    def __init__(self, config: dict[str, Any]):
        import trino
        self.connection = trino.dbapi.connect(
            host=config["host"], port=config["port"], user=config["user"],
            catalog=config["catalog"], schema=config["schema"],
            http_scheme=config.get("http_scheme", "http")
        )

    def execute(self, sql: str) -> list[dict[str, Any]]:
        cursor = self.connection.cursor()
        cursor.execute(sql)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
