from __future__ import annotations

import hmac
from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(frozen=True, slots=True)
class AdminAuthResult:
    ok: bool
    status: str
    admin_user_id: int | None


class AdminAccess:
    """Password-protected, persistent binding of one Telegram user as admin."""

    def __init__(self, database_path: Path, password: str) -> None:
        if not password:
            raise RuntimeError("ADMIN_PASSWORD is required in .env")
        self.database_path = database_path
        self.password = password

    async def init(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_admin (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    telegram_user_id INTEGER NOT NULL,
                    bound_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()

    async def admin_user_id(self) -> int | None:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                "SELECT telegram_user_id FROM runtime_admin WHERE singleton = 1"
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else None

    async def is_admin(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        return await self.admin_user_id() == user_id

    async def authenticate(self, user_id: int, password: str) -> AdminAuthResult:
        if not hmac.compare_digest(password, self.password):
            return AdminAuthResult(False, "wrong_password", await self.admin_user_id())

        current = await self.admin_user_id()
        if current is not None and current != user_id:
            return AdminAuthResult(False, "already_bound", current)

        if current == user_id:
            return AdminAuthResult(True, "already_admin", current)

        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO runtime_admin(singleton, telegram_user_id)
                VALUES (1, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    telegram_user_id = excluded.telegram_user_id,
                    bound_at = CURRENT_TIMESTAMP
                """,
                (user_id,),
            )
            await db.commit()
        return AdminAuthResult(True, "bound", user_id)
