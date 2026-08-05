from __future__ import annotations

import asyncio

from app.storage import Storage


def test_out_of_order_inserts_are_replayed_in_telegram_order(tmp_path) -> None:
    async def run() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()
        await storage.start_memory_recording(1, "ordered")

        source_ids = [502, 476, 489, 471, 501, 479, 482, 488]
        await asyncio.gather(
            *(
                storage.add_memory_message(
                    memory_id="ordered",
                    source_chat_id=123,
                    source_message_id=source_id,
                    content_type="text",
                    origin_label="test",
                )
                for source_id in source_ids
            )
        )

        rows = await storage.memory_messages("ordered")
        assert [row[0] for row in rows] == list(range(1, len(source_ids) + 1))
        assert [row[2] for row in rows] == sorted(source_ids)

    asyncio.run(run())


def test_duplicate_source_message_is_idempotent(tmp_path) -> None:
    async def run() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()
        await storage.start_memory_recording(1, "duplicate")

        first = await storage.add_memory_message(
            memory_id="duplicate",
            source_chat_id=123,
            source_message_id=500,
            content_type="sticker",
            origin_label="test",
        )
        second = await storage.add_memory_message(
            memory_id="duplicate",
            source_chat_id=123,
            source_message_id=500,
            content_type="sticker",
            origin_label="test",
        )

        assert first == second == 1
        assert len(await storage.memory_messages("duplicate")) == 1

    asyncio.run(run())
