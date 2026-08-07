from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from dotenv import load_dotenv

from app.admin_access import AdminAccess
from app.config import Settings, load_settings
from app.engine import QuestEngine
from app.memory_capture import capture_memory_message
from app.memory_modes import install_memory_mode_commands
from app.memory_variables import (
    MemoryVariable,
    collect_memory_variables,
    missing_memory_variables,
)
from app.roadmap import load_roadmap
from app.storage import Storage
from app.telegram import build_bot

if __name__ == "__main__":
    sys.modules.setdefault("app.main", sys.modules[__name__])

router = Router()
settings: Settings
storage: Storage
engine: QuestEngine
admin_access: AdminAccess
memory_variables: list[MemoryVariable]


async def is_admin(message: Message) -> bool:
    return bool(message.from_user and await admin_access.is_admin(message.from_user.id))


async def require_admin(message: Message) -> bool:
    if await is_admin(message):
        return True
    await message.answer(
        "Команда недоступна. Сначала авторизуйся через <code>/admin пароль</code>."
    )
    return False


def memory_variable(memory_id: str) -> MemoryVariable | None:
    return next((item for item in memory_variables if item.id == memory_id), None)


async def prompt_memory_setup(message: Message) -> None:
    if message.from_user is None:
        return

    total = len(memory_variables)
    if total == 0:
        await message.answer(
            "В ROADMAP пока нет блоков реконструкции воспоминаний. "
            "Добавь их в Roadmap Studio и экспортируй roadmap/quest.json."
        )
        return

    session = await storage.admin_session(message.from_user.id)
    if session and session[0] == "memory_record":
        variable = memory_variable(session[1])
        label = variable.label if variable else session[1]
        count = len(await storage.memory_messages(session[1]))
        await message.answer(
            f"Уже заполняется <code>{session[1]}</code> — {label}.\n"
            f"Принято сообщений: <b>{count}</b>.\n"
            "Пересылай сообщения по порядку, затем отправь /memory_done."
        )
        return

    missing = await missing_memory_variables(storage, memory_variables)
    filled = total - len(missing)
    if not missing:
        await message.answer(
            f"✅ Все переменные воспоминаний заполнены: <b>{total}/{total}</b>.\n"
            "Для проверки используй <code>/memory_preview ID</code>."
        )
        return

    current = missing[0]
    await storage.start_memory_recording(message.from_user.id, current.id)
    await message.answer(
        f"🧠 <b>Заполнение воспоминаний · {filled + 1}/{total}</b>\n\n"
        f"Переменная: <code>{current.id}</code>\n"
        f"Описание: {current.label}\n"
        f"Использований в ROADMAP: {current.usages}\n\n"
        "Теперь пересылай сюда настоящие сообщения из вашей переписки "
        "строго в нужном порядке. Когда закончишь — /memory_done.\n"
        "Отменить текущий режим: /memory_cancel."
    )


@router.message(Command("admin"))
async def admin_login(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    password = (command.args or "").strip()
    if password:
        with suppress(Exception):
            await message.delete()
    if not password:
        await message.answer("Формат: <code>/admin пароль</code>")
        return

    result = await admin_access.authenticate(message.from_user.id, password)
    if not result.ok:
        if result.status == "already_bound":
            await message.answer("Администратор уже назначен на другом Telegram-аккаунте.")
        else:
            await message.answer("Неверный пароль.")
        return

    if result.status == "bound":
        await message.answer("✅ Этот Telegram-аккаунт сохранён как администратор бота.")
    else:
        await message.answer("✅ Админ-режим подтверждён.")
    await prompt_memory_setup(message)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    if message.from_user is None:
        return
    if await admin_access.is_admin(message.from_user.id):
        await message.answer("Админ-режим активирован. /help_admin — список команд.")
        return

    if await admin_access.admin_user_id() is None:
        await message.answer("Бот ожидает первоначальной настройки.")
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
        "/start_quest — интро через задержку из .env\n"
        "/start_quest_now — запустить интро сразу\n"
        "/cancel_quest — отменить запуск\n"
        "/continue — продолжить после аварийной остановки\n"
        "/status — привязка, таймер и заполнение ROADMAP\n\n"
        "/memory_setup — заполнить все переменные из ROADMAP\n"
        "/memory_done — закончить текущую и перейти к следующей\n"
        "/memory_status — прогресс заполнения\n"
        "/memory_new &lt;id&gt; — ручная перезапись воспоминания\n"
        "/memory_save — закончить ручную запись\n"
        "/memory_cancel — выйти из записи\n"
        "/memory_list — список сохранённых воспоминаний\n"
        "/memory_mode — режимы отправки воспоминаний\n"
        "/memory_preview &lt;id&gt; — переслать воспоминание тебе\n"
        "/memory_play &lt;id&gt; — переслать воспоминание участнице"
    )


@router.message(Command("memory_setup"))
async def memory_setup(message: Message) -> None:
    if not await require_admin(message):
        return
    await prompt_memory_setup(message)


@router.message(Command("memory_status"))
async def memory_status(message: Message) -> None:
    if not await require_admin(message):
        return
    missing = await missing_memory_variables(storage, memory_variables)
    missing_ids = {item.id for item in missing}
    lines = []
    for item in memory_variables:
        marker = "❌" if item.id in missing_ids else "✅"
        count = len(await storage.memory_messages(item.id))
        lines.append(f"{marker} <code>{item.id}</code> — {count} сообщений · {item.label}")
    await message.answer(
        f"<b>Переменные воспоминаний: {len(memory_variables) - len(missing)}/{len(memory_variables)}</b>\n\n"
        + ("\n".join(lines) if lines else "В ROADMAP нет воспоминаний.")
    )


@router.message(Command("memory_done"))
async def memory_done(message: Message) -> None:
    if not await require_admin(message) or message.from_user is None:
        return
    session = await storage.admin_session(message.from_user.id)
    if not session or session[0] != "memory_record":
        await message.answer("Сейчас ни одно воспоминание не заполняется. /memory_setup")
        return

    memory_id = session[1]
    count = len(await storage.memory_messages(memory_id))
    if count == 0:
        await message.answer("Сначала перешли хотя бы одно настоящее сообщение.")
        return

    await storage.clear_admin_session(message.from_user.id)
    await message.answer(f"✅ <code>{memory_id}</code> сохранено: {count} сообщений.")
    await prompt_memory_setup(message)


@router.message(Command("start_quest"))
async def start_quest(message: Message) -> None:
    if not await require_admin(message):
        return
    participant = await storage.participant_chat_id()
    if participant is None:
        await message.answer("Сначала активируй бота на тестовом аккаунте командой /start.")
        return
    missing = await missing_memory_variables(storage, memory_variables)
    if missing:
        ids = ", ".join(item.id for item in missing)
        await message.answer(
            "Квест не запущен: не заполнены переменные воспоминаний:\n"
            f"<code>{ids}</code>\n\nЗапусти /memory_setup."
        )
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
    missing = await missing_memory_variables(storage, memory_variables)
    if missing:
        await message.answer("Сначала заполни все переменные через /memory_setup.")
        return
    step_id = engine.roadmap.meta.intro_step_id or engine.roadmap.meta.entry_step_id
    await engine.start(participant, step_id)
    failure = await engine.quest_failure(participant)
    if failure:
        await message.answer(
            "🚨 Запуск остановился на ошибке. Точка сохранена; после проверки используй /continue."
        )
    else:
        await message.answer("Тестовый запуск выполнен.")


@router.message(Command("cancel_quest"))
async def cancel_quest(message: Message) -> None:
    if not await require_admin(message):
        return
    await storage.cancel_quest()
    await message.answer("Запланированный запуск отменён.")


@router.message(Command("continue"))
async def continue_quest(message: Message) -> None:
    if not await require_admin(message):
        return
    participant = await storage.participant_chat_id()
    if participant is None:
        await message.answer("Участник ещё не привязан к боту.")
        return

    result = await engine.continue_quest(participant)
    markers = {
        "completed": "✅",
        "resumed": "▶️",
        "waiting": "ℹ️",
        "busy": "ℹ️",
        "missing": "ℹ️",
        "failed": "🚨",
    }
    await message.answer(f"{markers[result.status]} {result.message}")


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
    missing = await missing_memory_variables(storage, memory_variables)

    recovery_text = "нет активного квеста"
    if participant is not None:
        progress = await storage.get_progress(participant)
        failure = await engine.quest_failure(participant)
        if failure:
            recovery_text = "аварийная пауза — используй /continue"
        elif progress and progress.waiting:
            recovery_text = f"ожидание: {progress.waiting.get('kind', 'unknown')}"
        elif progress:
            recovery_text = "есть сохранённая точка выполнения"

    await message.answer(
        f"Участник: <code>{participant or 'не привязан'}</code>\n"
        f"Таймер: <code>{schedule_text}</code>\n"
        f"Прокси: <code>{proxy_state}</code>\n"
        f"ROADMAP: <code>{settings.roadmap_path}</code>\n"
        f"Воспоминания: <code>{len(memory_variables) - len(missing)}/{len(memory_variables)}</code>\n"
        f"Восстановление: <code>{recovery_text}</code>"
    )


@router.message(Command("memory_new"))
async def memory_new(message: Message, command: CommandObject) -> None:
    if not await require_admin(message) or message.from_user is None:
        return
    memory_id = (command.args or "").strip()
    if not memory_id or not memory_id.replace("-", "").replace("_", "").isalnum():
        await message.answer("Формат: /memory_new first_meeting")
        return
    await storage.start_memory_recording(message.from_user.id, memory_id)
    await message.answer(
        f"Ручная запись <code>{memory_id}</code> начата.\n"
        "Пересылай сообщения в нужном порядке.\n"
        "/memory_save — закончить, /memory_cancel — выйти."
    )


@router.message(Command("memory_save"))
async def memory_save(message: Message) -> None:
    if not await require_admin(message) or message.from_user is None:
        return
    session = await storage.admin_session(message.from_user.id)
    if not session or session[0] != "memory_record":
        await message.answer("Сейчас запись не идёт.")
        return
    memory_id = session[1]
    count = len(await storage.memory_messages(memory_id))
    await storage.clear_admin_session(message.from_user.id)
    await message.answer(f"Воспоминание <code>{memory_id}</code> сохранено: {count} сообщений.")


@router.message(Command("memory_cancel"))
async def memory_cancel(message: Message) -> None:
    if not await require_admin(message) or message.from_user is None:
        return
    await storage.clear_admin_session(message.from_user.id)
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
    await message.answer(f"Участнице отправлено: {count} сообщений.")


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
    if await admin_access.is_admin(message.from_user.id):
        session = await storage.admin_session(message.from_user.id)
        if session and session[0] == "memory_record":
            await capture_memory_message(
                storage,
                message,
                session[1],
                finish_command="/memory_done",
            )
        return

    participant = await storage.participant_chat_id()
    if participant == message.chat.id:
        await engine.handle_answer(message)


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
    global settings, storage, engine, admin_access, memory_variables

    load_dotenv()
    os.environ.setdefault("ADMIN_TELEGRAM_ID", "0")
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    root = Path(__file__).resolve().parents[1]
    roadmap_path = root / settings.roadmap_path
    roadmap = load_roadmap(roadmap_path)
    memory_variables = collect_memory_variables(roadmap_path)

    database_path = root / settings.database_path
    storage = Storage(database_path)
    await storage.init()
    admin_access = AdminAccess(database_path, os.getenv("ADMIN_PASSWORD", "").strip())
    await admin_access.init()

    if settings.sonya_telegram_id:
        await storage.bind_participant(settings.sonya_telegram_id)

    bot = build_bot(settings)
    engine = QuestEngine(bot, storage, roadmap, root)
    engine.configure_quest_recovery(admin_access.admin_user_id)
    install_memory_mode_commands(router)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    scheduler = asyncio.create_task(scheduler_loop())

    existing_admin = await admin_access.admin_user_id()
    if existing_admin is not None:
        missing = await missing_memory_variables(storage, memory_variables)
        if missing:
            with suppress(Exception):
                await bot.send_message(
                    existing_admin,
                    f"ROADMAP загружен. Не заполнено воспоминаний: "
                    f"<b>{len(missing)}/{len(memory_variables)}</b>.\n"
                    "Продолжить: /memory_setup",
                )

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
