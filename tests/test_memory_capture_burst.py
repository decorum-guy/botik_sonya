from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.memory_capture import capture_memory_message
from app.storage import Storage


class BurstMessage:
    def __init__(self, message_id: int) -> None:
        self.content_type = "text"
        self.text = f"message {message_id}"
        self.caption = None
        self.video_note = None
        self.sticker = None
        self.entities = None
        self.caption_entities = None
        self.forward_origin = SimpleNamespace()
        self.media_group_id = None
        self.chat = SimpleNamespace(id=123)
        self.from_user = None
        self.message_id = message_id

    async def answer(self, text: str) -> None:
        return None


def test_bulk_forward_is_saved_without_position_collisions(tmp_path) -> None:
    async def run() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()
        await storage.start_memory_recording(1, "burst")

        messages = [BurstMessage(message_id) for message_id in range(1000, 1040)]
        positions = await asyncio.gather(
            *(
                capture_memory_message(
                    storage,
                    message,
                    "burst",
                    finish_command="/memory_done",
                )
                for message in messages
            )
        )

        stored = await storage.memory_messages("burst")
        assert len(stored) == 40
        assert sorted(position for position in positions if position is not None) == list(
            range(1, 41)
        )
        assert {row[2] for row in stored} == set(range(1000, 1040))

    asyncio.run(run())
