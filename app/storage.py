from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


@dataclass(slots=True)
class Progress:
    chat_id: int
    step_id: str
    action_index: int
    waiting: dict | None
    wrong_index: int


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quest_schedule (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    run_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS progress (
                    chat_id INTEGER PRIMARY KEY,
                    step_id TEXT NOT NULL,
                    action_index INTEGER NOT NULL DEFAULT 0,
                    waiting_json TEXT,
                    wrong_index INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_messages (
                    memory_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    origin_label TEXT,
                    PRIMARY KEY (memory_id, position),
                    FOREIGN KEY (memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS admin_session (
                    admin_id INTEGER PRIMARY KEY,
                    mode TEXT,
                    payload TEXT
                );
                """
            )
            await db.commit()

    async def get_setting(self, key: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute("SELECT value FROM settings WHERE key = ?", (key,))).fetchone()
            return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            await db.commit()

    async def participant_chat_id(self) -> int | None:
        value = await self.get_setting("participant_chat_id")
        return int(value) if value else None

    async def bind_participant(self, chat_id: int) -> None:
        await self.set_setting("participant_chat_id", str(chat_id))

    async def schedule_quest(self, run_at: datetime) -> None:
        value = run_at.astimezone(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO quest_schedule(id, run_at, status) VALUES(1, ?, 'pending') "
                "ON CONFLICT(id) DO UPDATE SET run_at = excluded.run_at, status = 'pending'",
                (value,),
            )
            await db.commit()

    async def cancel_quest(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM quest_schedule WHERE id = 1")
            await db.commit()

    async def get_schedule(self) -> tuple[datetime, str] | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute("SELECT run_at, status FROM quest_schedule WHERE id = 1")).fetchone()
            if not row:
                return None
            return datetime.fromisoformat(row[0]), row[1]

    async def claim_due_quest(self, now: datetime) -> bool:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT run_at, status FROM quest_schedule WHERE id = 1"
            )).fetchone()
            if not row or row[1] != "pending" or datetime.fromisoformat(row[0]) > now.astimezone(UTC):
                await db.rollback()
                return False
            await db.execute("UPDATE quest_schedule SET status = 'running' WHERE id = 1")
            await db.commit()
            return True

    async def mark_quest_sent(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE quest_schedule SET status = 'sent' WHERE id = 1")
            await db.commit()

    async def mark_quest_failed(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE quest_schedule SET status = 'pending' WHERE id = 1")
            await db.commit()

    async def set_progress(
        self,
        chat_id: int,
        step_id: str,
        action_index: int,
        waiting: dict | None = None,
        wrong_index: int = 0,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO progress(chat_id, step_id, action_index, waiting_json, wrong_index)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    step_id = excluded.step_id,
                    action_index = excluded.action_index,
                    waiting_json = excluded.waiting_json,
                    wrong_index = excluded.wrong_index
                """,
                (chat_id, step_id, action_index, json.dumps(waiting) if waiting else None, wrong_index),
            )
            await db.commit()

    async def get_progress(self, chat_id: int) -> Progress | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT step_id, action_index, waiting_json, wrong_index FROM progress WHERE chat_id = ?",
                (chat_id,),
            )).fetchone()
            if not row:
                return None
            return Progress(
                chat_id=chat_id,
                step_id=row[0],
                action_index=row[1],
                waiting=json.loads(row[2]) if row[2] else None,
                wrong_index=row[3],
            )

    async def clear_progress(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM progress WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def start_memory_recording(self, admin_id: int, memory_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO memories(memory_id, created_at) VALUES(?, ?)",
                (memory_id, datetime.now(UTC).isoformat()),
            )
            await db.execute("DELETE FROM memory_messages WHERE memory_id = ?", (memory_id,))
            await db.execute(
                "INSERT INTO admin_session(admin_id, mode, payload) VALUES(?, 'memory_record', ?) "
                "ON CONFLICT(admin_id) DO UPDATE SET mode = excluded.mode, payload = excluded.payload",
                (admin_id, memory_id),
            )
            await db.commit()

    async def admin_session(self, admin_id: int) -> tuple[str, str] | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT mode, payload FROM admin_session WHERE admin_id = ?", (admin_id,)
            )).fetchone()
            return (row[0], row[1]) if row and row[0] else None

    async def clear_admin_session(self, admin_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM admin_session WHERE admin_id = ?", (admin_id,))
            await db.commit()

    async def add_memory_message(
        self,
        memory_id: str,
        source_chat_id: int,
        source_message_id: int,
        content_type: str,
        origin_label: str | None,
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM memory_messages WHERE memory_id = ?",
                (memory_id,),
            )).fetchone()
            position = int(row[0])
            await db.execute(
                """
                INSERT INTO memory_messages(
                    memory_id, position, source_chat_id, source_message_id, content_type, origin_label
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (memory_id, position, source_chat_id, source_message_id, content_type, origin_label),
            )
            await db.commit()
            return position

    async def memory_messages(self, memory_id: str) -> list[tuple[int, int, int, str, str | None]]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                """
                SELECT position, source_chat_id, source_message_id, content_type, origin_label
                FROM memory_messages WHERE memory_id = ? ORDER BY position
                """,
                (memory_id,),
            )).fetchall()
            return [(int(r[0]), int(r[1]), int(r[2]), str(r[3]), r[4]) for r in rows]

    async def list_memories(self) -> list[tuple[str, int]]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                """
                SELECT m.memory_id, COUNT(mm.position)
                FROM memories m LEFT JOIN memory_messages mm ON mm.memory_id = m.memory_id
                GROUP BY m.memory_id ORDER BY m.created_at
                """
            )).fetchall()
            return [(str(row[0]), int(row[1])) for row in rows]
