from __future__ import annotations

import asyncio

from app.storage import Storage


def test_users_are_persisted_and_updated(tmp_path) -> None:
    async def scenario() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()

        await storage.remember_user(
            user_id=101,
            chat_id=101,
            username="first_name",
            first_name="Артём",
            last_name=None,
        )
        await storage.remember_user(
            user_id=202,
            chat_id=202,
            username=None,
            first_name="Соня",
            last_name="Тестовая",
        )
        await storage.remember_user(
            user_id=101,
            chat_id=101,
            username="artem",
            first_name="Артём",
            last_name="Админ",
        )

        users = await storage.list_users()
        by_id = {user.user_id: user for user in users}

        assert set(by_id) == {101, 202}
        assert by_id[101].username == "artem"
        assert by_id[101].display_name == "Артём Админ"
        assert by_id[202].display_name == "Соня Тестовая"
        assert await storage.known_user_by_chat_id(202) == by_id[202]
        assert await storage.known_user_by_chat_id(999) is None

    asyncio.run(scenario())


def test_editor_memory_mode_and_message_count(tmp_path) -> None:
    async def scenario() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()

        await storage.start_memory_recording(
            101,
            "first_chat",
            mode="memory_editor",
        )
        assert await storage.admin_session(101) == ("memory_editor", "first_chat")
        assert await storage.memory_message_count("first_chat") == 0

        position = await storage.add_memory_message(
            memory_id="first_chat",
            source_chat_id=101,
            source_message_id=777,
            content_type="text",
            origin_label="MessageOriginUser",
        )
        assert position == 1
        assert await storage.memory_message_count("first_chat") == 1

        await storage.clear_admin_session(101)
        assert await storage.admin_session(101) is None

    asyncio.run(scenario())
