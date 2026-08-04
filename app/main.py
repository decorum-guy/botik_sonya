from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import Settings, load_settings
from app.engine import QuestEngine
from app.roadmap import load_roadmap
from app.storage import Storage
from app.telegram import build_bot

router = Router()
settings: Settings
storage: Storage
engine: QuestEngine


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.admin_telegram_id)


async def require_admin(message: Message) -> bool:
    if is_admin(message):
        return True
    await message.answer("Команда недоступна.")
    return False


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    if message.from_user is None:
        return
    if message.from_user.id == settings.admin_telegram_id:
        await message.answer("Админ-режим активирован. /help_admin — список тестовых команд.")
        return

    configured = settings.sonya_telegram_id
    bound = await storage.participant_chat_id()
    if configured and message.from_user.id != configured:
        await message.answer("Этот бот уже настроен для другого пользователя.")
        return
    if bound and bound != message.chat.id:
        await message.answer("Этот бот уже активирован.")
        return
    await storage.bind_participant(message.chat.id)
    await message.answer("Бот активирован")


@router.message(Command("help_admin"))
async def help_admin(message: Message) -> None:
    if not await require_admin(message):
        return
    await message.answer(
        "<b>Управление тестовой версией</b>\n\n"
        "/start_quest — запланировать интро через задержку из .env\n"
        "/start_quest_now — запустить интро сразу\n"
        "/cancel_quest — отменить запуск\n"
        "/status — состояние привязки и таймера\n\n"
        "/memory_new &lt;id&gt; — начать запись воспоминания\n"
        "/memory_save — закончить запись\n"
        "/memory_cancel — отменить режим записи\n"
        "/memory_list — список воспоминаний\n"
        "/memory_preview &lt;id&gt; — переслать воспоминание тебе\n"
        "/memory_play &lt;id&gt; — переслать воспоминание Соне"
    )


@router.message(Command("start_quest"))
async def start_quest(message: Message) -> None:
    if not await require_admin(message):
        return
    participant = await storage.participant_chat_id()
    if participant is None:
        await message.answer("Сначала активируй бота на телефоне Сони командой /start.")
        return
    run_at = datetime.now(UTC) + timedelta(seconds=settings.quest_start_delay_seconds)
    await storage.schedule_quest(run_at)
    await message.answer(
        f"Квест запланирован. Интро будет отправлено через "
        f"{settings.quest_start_delay_seconds} сек.\n"
        f"UTC: <code>{run_at.isoformat(timespec='seconds')}</code>"
    )


@router.message(Command("start_quest_now"))
async def start_quest_now(message: Message) -> None:
    if not await require_admin(message):
        return
    participant = await storage.participant_chat_id()
    if participant is None:
        await message.answer("Участник ещё не активировал бота.")
        return
    step_id = engine.roadmap.meta.intro_step_id or engine.roadmap.meta.entry_step_id
    await engine.start(participant, step_id)
    await message.answer("Тестовый запуск выполнен.")


@router.message(Command("cancel_quest"))
async def cancel_quest(message: Message) -> None:
    if not await require_admin(message):
        return
    await storage.cancel_quest()
    await message.answer("Запланированный запуск отменён.")


@router.message(Command("status"))
async def status(message: Message) -> None:
    if not await require_admin(message):
        return
    participant = await storage.participant_chat_id()
    schedule = await storage.get_schedule()
    proxy_state = "включён" if settings.proxy_url else "не задан"
    schedule_text = "нет"
    if schedule:
        schedule_text = f"{schedule[0].isoformat()} · {schedule[1]}"
    await message.answer(
        f"Участник: <code>{participant or 'не привязан'}</code>\n"
        f"Таймер: <code>{schedule_text}</code>\n"
        f"Прокси: <code>{proxy_state}</code>\n"
        f"ROADMAP: <code>{settings.roadmap_path}</code>"
    )


@router.message(Command("memory_new"))
async def memory_new(message: Message, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    memory_id = (command.args or "").strip()
    if not memory_id or not memory_id.replace("-", "").replace("_", "").isalnum():
        await message.answer("Формат: /memory_new first_meeting")
        return
    await storage.start_memory_recording(message.from_user.id, memory_id)  # type: ignore[union-attr]
    await message.answer(
        f"Запись <code>{memory_id}</code> начата.\n"
        "Теперь пересылай сюда сообщения в нужном порядке.\n"
        "/memory_save — закончить, /memory_cancel — выйти без продолжения."
    )


@router.message(Command("memory_save"))
async def memory_save(message: Message) -> None:
    if not await require_admin(message):
        return
    session = await storage.admin_session(message.from_user.id)  # type: ignore[union-attr]
    if not session or session[0] != "memory_record":
        await message.answer("Сейчас запись не идёт.")
        return
    memory_id = session[1]
    count = len(await storage.memory_messages(memory_id))
    await storage.clear_admin_session(message.from_user.id)  # type: ignore[union-attr]
    await message.answer(f"Воспоминание <code>{memory_id}</code> сохранено: {count} сообщений.")


@router.message(Command("memory_cancel"))
async def memory_cancel(message: Message) -> None:
    if not await require_admin(message):
        return
    await storage.clear_admin_session(message.from_user.id)  # type: ignore[union-attr]
    await message.answer("Режим записи выключен. Уже принятые сообщения не удалены.")


@router.message(Command("memory_list"))
async def memory_list(message: Message) -> None:
    if not await require_admin(message):
        return
    items = await storage.list_memories()
    text = "\n".join(f"• <code>{key}</code> — {count}" for key, count in items) or "Пока пусто."
    await message.answer(text)


@router.message(Command("memory_preview"))
async def memory_preview(message: Message, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    memory_id = (command.args or "").strip()
    if not memory_id:
        await message.answer("Формат: /memory_preview first_meeting")
        return
    count = await engine.preview_memory(message.chat.id, memory_id)
    await message.answer(f"Предпросмотр завершён: {count} сообщений.")


@router.message(Command("memory_play"))
async def memory_play(message: Message, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    memory_id = (command.args or "").strip()
    participant = await storage.participant_chat_id()
    if not memory_id or participant is None:
        await message.answer("Нужны ID воспоминания и привязанный участник.")
        return
    count = await engine.preview_memory(participant, memory_id)
    await message.answer(f"Соне отправлено: {count} сообщений.")


@router.callback_query(F.data.startswith("quest:"))
async def quest_button(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        return
    button_id = callback.data.removeprefix("quest:")
    ok, note = await engine.handle_button(callback.message.chat.id, button_id)
    await callback.answer(note or ("Принято" if ok else "Неактивно"), show_alert=not ok)
    if ok:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.message()
async def catch_all(message: Message) -> None:
    if message.from_user is None:
        return
    if message.from_user.id == settings.admin_telegram_id:
        session = await storage.admin_session(message.from_user.id)
        if session and session[0] == "memory_record":
            origin = message.forward_origin
            origin_label = type(origin).__name__ if origin else None
            position = await storage.add_memory_message(
                memory_id=session[1],
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                content_type=message.content_type,
                origin_label=origin_label,
            )
            await message.answer(f"Сохранено #{position}: <code>{message.content_type}</code>")
        return

    participant = await storage.participant_chat_id()
    if participant == message.chat.id:
        handled = await engine.handle_answer(message)
        if not handled:
            return


async def scheduler_loop() -> None:
    while True:
        try:
            if await storage.claim_due_quest(datetime.now(UTC)):
                participant = await storage.participant_chat_id()
                if participant is None:
                    await storage.mark_quest_failed()
                else:
                    step_id = engine.roadmap.meta.intro_step_id or engine.roadmap.meta.entry_step_id
                    try:
                        await engine.start(participant, step_id)
                    except Exception:
                        logging.exception("Scheduled quest start failed")
                        await storage.mark_quest_failed()
                    else:
                        await storage.mark_quest_sent()
        except Exception:
            logging.exception("Scheduler iteration failed")
        await asyncio.sleep(1)


async def main() -> None:
    global settings, storage, engine
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root = Path(__file__).resolve().parents[1]
    roadmap = load_roadmap(root / settings.roadmap_path)
    storage = Storage(root / settings.database_path)
    await storage.init()
    if settings.sonya_telegram_id:
        await storage.bind_participant(settings.sonya_telegram_id)

    bot = build_bot(settings)
    engine = QuestEngine(bot, storage, roadmap, root)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    scheduler = asyncio.create_task(scheduler_loop())
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
