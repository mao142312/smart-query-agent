from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

from smart_ask_data.health import unavailable_data_source


class SQLiteDemoClient:
    """Deterministic local query engine mirroring the tables used by generated SQL."""

    def __init__(self):
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._seed()
        self.connection.execute("PRAGMA query_only = ON")
        self.connection.set_authorizer(self._authorize_read_only)

    @staticmethod
    def _authorize_read_only(action: int, _arg1, _arg2, _database, _source) -> int:
        denied_actions = {
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_ANALYZE,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_TEMP_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_INDEX,
            sqlite3.SQLITE_DROP_TEMP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_TRIGGER,
            sqlite3.SQLITE_DROP_TEMP_VIEW,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_PRAGMA,
            sqlite3.SQLITE_REINDEX,
            sqlite3.SQLITE_UPDATE,
        }
        return sqlite3.SQLITE_DENY if action in denied_actions else sqlite3.SQLITE_OK

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
        today = datetime.now().astimezone().date()
        openings = []
        transactions = []
        regions = ["香港", "上海", "北京"]
        for days_ago in range(15):
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
        with self._lock:
            cursor = self.connection.execute(sql)
            return [dict(row) for row in cursor.fetchall()]

    def health_check(self) -> dict[str, Any]:
        try:
            with self._lock:
                row = self.connection.execute("SELECT 1 AS ok").fetchone()
            if row is None or row["ok"] != 1:
                raise RuntimeError("data source probe returned an unexpected result")
            return {
                "status": "ok",
                "backend": "sqlite",
                "read_only": True,
                "read_only_basis": "isolated_demo_database",
            }
        except Exception as exc:  # noqa: BLE001 - database drivers expose backend-specific exceptions
            return unavailable_data_source(
                "sqlite", True, "isolated_demo_database", exc
            )

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001, S110 - destructor cleanup must never escape
            pass


class TrinoClient:
    def __init__(self, config: dict[str, Any]):
        import trino
        read_only = config.get("read_only")
        if not isinstance(read_only, bool):
            raise TypeError("trino.read_only 必须显式配置为布尔值")
        self.read_only = read_only
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

    def health_check(self) -> dict[str, Any]:
        if not self.read_only:
            return {
                "status": "error",
                "backend": "trino",
                "read_only": False,
                "read_only_basis": "declared_by_configuration",
                "error": {
                    "code": "DATA_SOURCE_NOT_READ_ONLY",
                    "message": "数据源未声明为只读",
                },
            }
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            if row is None or row[0] != 1:
                raise RuntimeError("data source probe returned an unexpected result")
            return {
                "status": "ok",
                "backend": "trino",
                "read_only": self.read_only,
                "read_only_basis": "declared_by_configuration",
            }
        except Exception as exc:  # noqa: BLE001 - database drivers expose backend-specific exceptions
            return unavailable_data_source(
                "trino", self.read_only, "declared_by_configuration", exc
            )
