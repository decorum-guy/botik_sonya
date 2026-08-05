from __future__ import annotations

import html
import logging
import sys
import time
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)

PING_TIMEOUT_SECONDS = 15


def _state_module() -> Any:
    # Imported lazily to avoid a circular import while app.main itself imports
    # build_bot from app.telegram.
    import app.main as bot_app

    return bot_app


def _is_ping_message(message: Message) -> bool:
    command = (message.text or "").strip().split(maxsplit=1)[0]
    command = command.split("@", 1)[0].lower()
    return command == "/ping"


def _protect_ping_from_builder_filters() -> None:
    """Keep Roadmap Studio input filters from consuming /ping as quest content."""

    for module in tuple(sys.modules.values()):
        spec_name = getattr(getattr(module, "__spec__", None), "name", None)
        module_name = getattr(module, "__name__", None)
        if spec_name != "tools.builder_server" and module_name != "tools.builder_server":
            continue

        for class_name in ("ActiveTestInputFilter", "EditorMemoryMessageFilter"):
            filter_class = getattr(module, class_name, None)
            if filter_class is None or getattr(filter_class, "_ping_guard_installed", False):
                continue
            original_call = filter_class.__call__

            async def guarded_call(self, message, _original_call=original_call):
                if _is_ping_message(message):
                    return False
                return await _original_call(self, message)

            filter_class.__call__ = guarded_call
            filter_class._ping_guard_installed = True


async def admin_ping(message: Message) -> None:
    state = _state_module()
    admin_access = getattr(state, "admin_access", None)
    if (
        message.from_user is None
        or admin_access is None
        or not await admin_access.is_admin(message.from_user.id)
    ):
        await message.answer(
            "Команда недоступна. Сначала авторизуйся через /admin <пароль>."
        )
        return

    lines = ["🏓 <b>Проверка бота</b>"]
    all_ok = True

    started = time.perf_counter()
    try:
        bot_user = await message.bot.get_me(request_timeout=PING_TIMEOUT_SECONDS)
        latency_ms = round((time.perf_counter() - started) * 1000)
        username = f"@{bot_user.username}" if bot_user.username else str(bot_user.id)
        lines.append(
            f"✅ Telegram API: <code>{html.escape(username)}</code> · {latency_ms} мс"
        )
    except Exception as exc:
        all_ok = False
        lines.append(
            "❌ Telegram API: "
            f"<code>{html.escape(type(exc).__name__)}</code> — "
            f"{html.escape(str(exc))}"
        )
        logger.exception("Admin /ping Telegram API check failed")

    settings = getattr(state, "settings", None)
    proxy_configured = bool(getattr(settings, "proxy_url", None))
    if proxy_configured and all_ok:
        lines.append("✅ Прокси: настроен, запрос к Telegram прошёл")
    elif proxy_configured:
        lines.append("❌ Прокси: настроен, но Telegram API не ответил")
    else:
        all_ok = False
        lines.append("⚠️ Прокси: не задан в PROXY_URL")

    storage = getattr(state, "storage", None)
    try:
        if storage is None:
            raise RuntimeError("Storage is not initialized")
        participant = await storage.participant_chat_id()
        await storage.get_schedule()
        lines.append(
            "✅ База данных: доступна · участник "
            f"<code>{participant or 'не привязан'}</code>"
        )
    except Exception as exc:
        all_ok = False
        lines.append(
            "❌ База данных: "
            f"<code>{html.escape(type(exc).__name__)}</code> — "
            f"{html.escape(str(exc))}"
        )
        logger.exception("Admin /ping database check failed")

    engine = getattr(state, "engine", None)
    try:
        if engine is None:
            raise RuntimeError("Quest engine is not initialized")
        roadmap = engine.roadmap
        entry = roadmap.meta.entry_step_id
        lines.append(
            f"✅ ROADMAP: {len(roadmap.steps)} этапов · вход <code>{html.escape(entry)}</code>"
        )
    except Exception as exc:
        all_ok = False
        lines.append(
            "❌ ROADMAP: "
            f"<code>{html.escape(type(exc).__name__)}</code> — "
            f"{html.escape(str(exc))}"
        )
        logger.exception("Admin /ping roadmap check failed")

    lines.append("✅ Polling: команда получена и обработана")
    lines.append(
        "\n<b>Итог:</b> "
        + ("бот исправен" if all_ok else "обнаружена проблема — смотри пункты выше")
    )
    await message.answer("\n".join(lines))


def install_admin_ping(router: Router) -> None:
    if getattr(router, "_admin_ping_installed", False):
        return

    _protect_ping_from_builder_filters()

    # app.main has a final catch-all message handler. Register normally and then
    # move /ping to the front so the generic handler cannot swallow the command.
    router.message.register(admin_ping, Command("ping"))
    handler = router.message.handlers.pop()
    router.message.handlers.insert(0, handler)
    router._admin_ping_installed = True
