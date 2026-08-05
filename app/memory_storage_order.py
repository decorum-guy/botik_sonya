from __future__ import annotations

from typing import Any

import aiosqlite


POSITION_SHIFT = 1_000_000_000


def install_memory_storage_order(storage_module: Any) -> None:
    """Make memory inserts atomic and keep Telegram source-message order.

    Bulk forwards are dispatched concurrently and may reach handlers out of order.
    The message IDs in the private admin-bot chat still reflect the order selected
    by the user, so every insert renumbers the memory by ``source_message_id``.
    """

    storage_class = storage_module.Storage
    if getattr(storage_class, "_ordered_memory_storage_installed", False):
        return

    async def add_memory_message(
        self,
        memory_id: str,
        source_chat_id: int,
        source_message_id: int,
        content_type: str,
        origin_label: str | None,
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")

            existing = await (
                await db.execute(
                    """
                    SELECT position
                    FROM memory_messages
                    WHERE memory_id = ?
                      AND source_chat_id = ?
                      AND source_message_id = ?
                    """,
                    (memory_id, source_chat_id, source_message_id),
                )
            ).fetchone()
            if existing is not None:
                await db.rollback()
                return int(existing[0])

            row = await (
                await db.execute(
                    """
                    SELECT COALESCE(MAX(position), 0) + 1
                    FROM memory_messages
                    WHERE memory_id = ?
                    """,
                    (memory_id,),
                )
            ).fetchone()
            temporary_position = int(row[0])
            cursor = await db.execute(
                """
                INSERT INTO memory_messages(
                    memory_id,
                    position,
                    source_chat_id,
                    source_message_id,
                    content_type,
                    origin_label
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    temporary_position,
                    source_chat_id,
                    source_message_id,
                    content_type,
                    origin_label,
                ),
            )
            inserted_rowid = int(cursor.lastrowid)

            rows = await (
                await db.execute(
                    """
                    SELECT rowid
                    FROM memory_messages
                    WHERE memory_id = ?
                    ORDER BY source_message_id, rowid
                    """,
                    (memory_id,),
                )
            ).fetchall()

            # Move all current positions outside the normal range first, so the
            # primary key cannot collide while assigning 1..N in source order.
            await db.execute(
                """
                UPDATE memory_messages
                SET position = position + ?
                WHERE memory_id = ?
                """,
                (POSITION_SHIFT, memory_id),
            )

            inserted_position: int | None = None
            for position, (rowid,) in enumerate(rows, start=1):
                await db.execute(
                    "UPDATE memory_messages SET position = ? WHERE rowid = ?",
                    (position, int(rowid)),
                )
                if int(rowid) == inserted_rowid:
                    inserted_position = position

            await db.commit()
            if inserted_position is None:  # pragma: no cover - database invariant
                raise RuntimeError("Inserted memory message disappeared during ordering")
            return inserted_position

    async def memory_messages(
        self,
        memory_id: str,
    ) -> list[tuple[int, int, int, str, str | None]]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    """
                    SELECT position, source_chat_id, source_message_id, content_type, origin_label
                    FROM memory_messages
                    WHERE memory_id = ?
                    ORDER BY position
                    """,
                    (memory_id,),
                )
            ).fetchall()
        return [
            (int(row[0]), int(row[1]), int(row[2]), str(row[3]), row[4])
            for row in rows
        ]

    storage_class.add_memory_message = add_memory_message
    storage_class.memory_messages = memory_messages
    storage_class._ordered_memory_storage_installed = True
