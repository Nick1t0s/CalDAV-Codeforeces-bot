import json
from collections.abc import Mapping
from typing import Any

import aiosqlite
from aiogram.exceptions import DataNotDictLikeError
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from config import DB_URL

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS fsm_states (
    key TEXT PRIMARY KEY,
    state TEXT,
    data TEXT NOT NULL DEFAULT '{}'
)
"""


def _db_path() -> str:
    prefix = "sqlite+aiosqlite:///"
    if DB_URL.startswith(prefix):
        return DB_URL[len(prefix):] or "bot.db"
    raise RuntimeError("SQLiteStorage supports only sqlite+aiosqlite DSN")


class SQLiteStorage(BaseStorage):
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _db_path()
        self._conn: aiosqlite.Connection | None = None

    async def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            await self._conn.execute(_CREATE_SQL)
            await self._conn.commit()
        return self._conn

    @staticmethod
    def _make_key(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}"

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        conn = await self._connection()
        state_str = state.state if isinstance(state, State) else state
        await conn.execute(
            "INSERT INTO fsm_states (key, state, data) VALUES (?, ?, '{}') "
            "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
            (self._make_key(key), state_str),
        )
        await conn.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        conn = await self._connection()
        cur = await conn.execute("SELECT state FROM fsm_states WHERE key = ?", (self._make_key(key),))
        row = await cur.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if not isinstance(data, dict):
            msg = f"Data must be a dict or dict-like object, got {type(data).__name__}"
            raise DataNotDictLikeError(msg)
        conn = await self._connection()
        payload = json.dumps(data, ensure_ascii=False)
        await conn.execute(
            "INSERT INTO fsm_states (key, state, data) VALUES (?, NULL, ?) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
            (self._make_key(key), payload),
        )
        await conn.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        conn = await self._connection()
        cur = await conn.execute("SELECT data FROM fsm_states WHERE key = ?", (self._make_key(key),))
        row = await cur.fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
