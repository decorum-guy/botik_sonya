from __future__ import annotations

import asyncio
import html
import logging
import os
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, Message
from dotenv import load_dotenv
from pydantic import ValidationError

import app.main as bot_app
from app.admin_access import AdminAccess
from app.builder_api import BuilderApiError, prepare_test_roadmap
from app.config import load_settings
from app.engine import QuestEngine
from app.memory_variables import collect_memory_variables
from app.models import MemoryAction, Roadmap
from app.roadmap import load_roadmap
from app.storage import BotUser, Storage
from app.telegram import build_bot
from app.user_tracking import UserTrackingMiddleware

logger = logging.getLogger(__name__)


class ActiveTestInputFilter(Filter):
    def __init__(self, storage: Storage, engines: dict[int, QuestEngine]) -> None:
        self.storage = storage
        self.engines = engines

    async def __call__(self, message: Message) -> bool:
        if message.chat.id not in self.engines:
            return False
        progress = await self.storage.get_progress(message.chat.id)
        return bool(
            progress
            and progress.waiting
            and progress.waiting.get("kind") == "input"
        )


class ActiveTestButtonFilter(Filter):
    def __init__(self, engines: dict[int, QuestEngine]) -> None:
        self.engines = engines

    async def __call__(self, callback: CallbackQuery) -> bool:
        return bool(
            callback.data
            and callback.data.startswith("quest:")
            and callback.message
            and callback.message.chat.id in self.engines
        )


class EditorMemoryMessageFilter(Filter):
    def __init__(self, storage: Storage, admin_access: AdminAccess) -> None:
        self.storage = storage
        self.admin_access = admin_access

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not await self.admin_access.is_admin(message.from_user.id):
            return False
        session = await self.storage.admin_session(message.from_user.id)
        return bool(session and session[0] == "memory_editor")


def build_studio_router(
    storage: Storage,
    admin_access: AdminAccess,
    active_test_engines: dict[int, QuestEngine],
) -> Router:
    router = Router(name="roadmap_studio")

    @router.message(Command("end"))
    async def end_editor_memory(message: Message) -> None:
        if message.from_user is None or not await admin_access.is_admin(message.from_user.id):
            await message.answer("Команда /end доступна только администратору.")
            return
        session = await storage.admin_session(message.from_user.id)
        if not session or session[0] != "memory_editor":
            await message.answer("Сейчас воспоминание из редактора не заполняется.")
            return
        memory_id = session[1]
        count = await storage.memory_message_count(memory_id)
        if count == 0:
            await message.answer("Сначала перешли хотя бы одно сообщение, затем отправь /end.")
            return
        await storage.clear_admin_session(message.from_user.id)
        await message.answer(
            f"✅ Воспоминание <code>{html.escape(memory_id)}</code> сохранено: "
            f"<b>{count}</b> сообщений."
        )

    @router.message(EditorMemoryMessageFilter(storage, admin_access))
    async def capture_editor_memory(message: Message) -> None:
        if message.from_user is None:
            return
        session = await storage.admin_session(message.from_user.id)
        if not session or session[0] != "memory_editor":
            return
        origin = message.forward_origin
        if origin is None:
            await message.answer(
                "Это сообщение не выглядит пересланным. Перешли оригинальное сообщение "
                "из вашей переписки. Когда закончишь — /end."
            )
            return
        position = await storage.add_memory_message(
            memory_id=session[1],
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
            content_type=message.content_type,
            origin_label=type(origin).__name__,
        )
        await message.answer(
            f"Сохранено #{position}: <code>{message.content_type}</code>. "
            "Когда закончишь — /end."
        )

    @router.callback_query(ActiveTestButtonFilter(active_test_engines), F.data.startswith("quest:"))
    async def test_button(callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        chat_id = callback.message.chat.id
        test_engine = active_test_engines[chat_id]
        button_id = callback.data.removeprefix("quest:")
        ok, note = await test_engine.handle_button(chat_id, button_id)
        await callback.answer(note or ("Принято" if ok else "Неактивно"), show_alert=not ok)
        if ok:
            with suppress(Exception):
                await callback.message.edit_reply_markup(reply_markup=None)

    @router.message(ActiveTestInputFilter(storage, active_test_engines))
    async def test_answer(message: Message) -> None:
        await active_test_engines[message.chat.id].handle_answer(message)

    return router


class RoadmapStudioServer:
    def __init__(
        self,
        root: Path,
        bot,
        storage: Storage,
        admin_access: AdminAccess,
        active_test_engines: dict[int, QuestEngine],
    ) -> None:
        self.root = root.resolve()
        self.builder_dir = (self.root / "builder").resolve()
        self.bot = bot
        self.storage = storage
        self.admin_access = admin_access
        self.active_test_engines = active_test_engines
        self.runner: web.AppRunner | None = None

    async def start(self, host: str, port: int) -> None:
        application = web.Application(client_max_size=8 * 1024 * 1024)
        application.router.add_get("/", self._redirect)
        application.router.add_get("/builder", self._redirect)
        application.router.add_get("/builder/", self._index)
        application.router.add_get("/api/test-status", self._status)
        application.router.add_get("/api/users", self._users)
        application.router.add_post("/api/test-run", self._run)
        application.router.add_post("/api/memory/start", self._start_memory)
        application.router.add_static("/builder/", self.builder_dir, show_index=False)

        self.runner = web.AppRunner(application)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host=host, port=port)
        try:
            await site.start()
        except OSError as exc:
            await self.close()
            raise RuntimeError(
                f"Порт {host}:{port} занят. Останови старый `python3 -m http.server` через Ctrl+C, "
                "затем снова запусти `python -m tools.builder_server`."
            ) from exc

        logger.info("Roadmap Studio запущен: http://%s:%s/builder/", host, port)

    async def close(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    async def _redirect(self, request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound("/builder/")

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(self.builder_dir / "index.html")

    async def _target_users(self) -> list[dict[str, Any]]:
        users_by_chat: dict[int, BotUser] = {
            user.chat_id: user for user in await self.storage.list_users()
        }
        admin_id = await self.admin_access.admin_user_id()
        participant_id = await self.storage.participant_chat_id()
        chat_ids = set(users_by_chat)
        if admin_id is not None:
            chat_ids.add(admin_id)
        if participant_id is not None:
            chat_ids.add(participant_id)

        result: list[dict[str, Any]] = []
        for chat_id in chat_ids:
            user = users_by_chat.get(chat_id)
            roles: list[str] = []
            if chat_id == admin_id:
                roles.append("админ")
            if chat_id == participant_id:
                roles.append("участник")

            if user is not None:
                label = user.display_name
                if user.username and f"@{user.username}" not in label:
                    label += f" · @{user.username}"
                user_id = user.user_id
                last_seen_at = user.last_seen_at
            else:
                label = "Администратор" if chat_id == admin_id else "Участник"
                user_id = chat_id
                last_seen_at = None

            if roles:
                label += f" · {', '.join(roles)}"
            result.append(
                {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "label": label,
                    "username": user.username if user else None,
                    "roles": roles,
                    "last_seen_at": last_seen_at,
                }
            )

        result.sort(key=lambda item: ("админ" not in item["roles"], item["label"].lower()))
        return result

    async def _status(self, request: web.Request) -> web.Response:
        users = await self._target_users()
        return web.json_response(
            {
                "ok": True,
                "known_users": len(users),
                "admin_available": await self.admin_access.admin_user_id() is not None,
            }
        )

    async def _users(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "users": await self._target_users()})

    async def _run(self, request: web.Request) -> web.Response:
        try:
            payload: dict[str, Any] = await request.json()
            roadmap = Roadmap.model_validate(payload.get("roadmap"))
            scope = str(payload.get("scope") or "full")
            step_id_value = payload.get("step_id")
            step_id = str(step_id_value) if step_id_value is not None else None
            action_index_value = payload.get("action_index")
            action_index = int(action_index_value) if action_index_value is not None else None
            target_chat_id = int(payload.get("target_chat_id"))

            known_chat_ids = {item["chat_id"] for item in await self._target_users()}
            if target_chat_id not in known_chat_ids:
                raise BuilderApiError(
                    "Выбранный пользователь ещё не писал боту. Отправь ему любое сообщение и обнови список."
                )

            test_roadmap, start_step_id = prepare_test_roadmap(
                roadmap,
                scope,
                step_id=step_id,
                action_index=action_index,
            )
            test_engine = QuestEngine(self.bot, self.storage, test_roadmap, self.root)
            self.active_test_engines[target_chat_id] = test_engine

            # Keep the legacy handlers compatible while the Studio router uses
            # the per-chat engine map for answers and inline buttons.
            bot_app.engine = test_engine
            await test_engine.start(target_chat_id, start_step_id)
        except (BuilderApiError, TypeError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else None
            message = first.get("msg") if first else str(exc)
            return web.json_response(
                {"ok": False, "error": f"ROADMAP не прошёл проверку: {message}"},
                status=400,
            )
        except Exception as exc:
            logger.exception("Не удалось запустить тест из Roadmap Studio")
            return web.json_response(
                {"ok": False, "error": f"Тестовый запуск не выполнен: {exc}"},
                status=400,
            )

        labels = {
            "full": "Весь сценарий запущен",
            "step": f"Этап {step_id} запущен",
            "action": f"Блок {(action_index or 0) + 1} запущен",
        }
        return web.json_response(
            {
                "ok": True,
                "message": f"{labels.get(scope, 'Сценарий запущен')} для chat_id {target_chat_id}.",
            }
        )

    async def _start_memory(self, request: web.Request) -> web.Response:
        try:
            payload: dict[str, Any] = await request.json()
            roadmap = Roadmap.model_validate(payload.get("roadmap"))
            step_id = str(payload.get("step_id") or "")
            action_index = int(payload.get("action_index"))
            replace = bool(payload.get("replace", False))

            step = roadmap.step(step_id)
            if action_index < 0 or action_index >= len(step.actions):
                raise BuilderApiError("Выбранный блок не найден.")
            action = step.actions[action_index]
            if not isinstance(action, MemoryAction):
                raise BuilderApiError("Сначала выбери блок «Воспоминание».")

            admin_id = await self.admin_access.admin_user_id()
            if admin_id is None:
                raise BuilderApiError("Сначала авторизуйся в боте командой /admin <пароль>.")

            count = await self.storage.memory_message_count(action.memory_id)
            if count > 0 and not replace:
                return web.json_response(
                    {
                        "ok": False,
                        "requires_confirmation": True,
                        "existing_count": count,
                        "memory_id": action.memory_id,
                        "error": (
                            f"Воспоминание {action.memory_id} уже содержит {count} сообщений. "
                            "Нужно подтверждение перезаписи."
                        ),
                    },
                    status=409,
                )

            await self.storage.start_memory_recording(
                admin_id,
                action.memory_id,
                mode="memory_editor",
            )
            await self.bot.send_message(
                admin_id,
                "🧠 <b>Наполнение воспоминания из Roadmap Studio</b>\n\n"
                f"ID: <code>{html.escape(action.memory_id)}</code>\n"
                f"Заголовок: {html.escape(action.title)}\n\n"
                "Пересылай настоящие сообщения из вашей переписки строго по порядку. "
                "Когда закончишь — отправь /end.",
            )
        except (BuilderApiError, KeyError, TypeError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else None
            message = first.get("msg") if first else str(exc)
            return web.json_response(
                {"ok": False, "error": f"ROADMAP не прошёл проверку: {message}"},
                status=400,
            )
        except Exception as exc:
            logger.exception("Не удалось начать наполнение воспоминания")
            return web.json_response(
                {"ok": False, "error": f"Не удалось активировать запись: {exc}"},
                status=400,
            )

        return web.json_response(
            {
                "ok": True,
                "message": (
                    f"Бот попросил админа наполнить воспоминание {action.memory_id}. "
                    "Завершение — /end."
                ),
            }
        )


async def main() -> None:
    load_dotenv()
    os.environ.setdefault("ADMIN_TELEGRAM_ID", "0")
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    root = Path(__file__).resolve().parents[1]
    roadmap_path = root / settings.roadmap_path
    database_path = root / settings.database_path

    roadmap = load_roadmap(roadmap_path)
    storage = Storage(database_path)
    await storage.init()
    admin_access = AdminAccess(database_path, os.getenv("ADMIN_PASSWORD", "").strip())
    await admin_access.init()

    if settings.sonya_telegram_id:
        await storage.bind_participant(settings.sonya_telegram_id)

    bot = build_bot(settings)
    bot_app.settings = settings
    bot_app.storage = storage
    bot_app.admin_access = admin_access
    bot_app.memory_variables = collect_memory_variables(roadmap_path)
    bot_app.engine = QuestEngine(bot, storage, roadmap, root)

    active_test_engines: dict[int, QuestEngine] = {}
    dispatcher = Dispatcher()
    tracking = UserTrackingMiddleware(storage)
    dispatcher.message.outer_middleware(tracking)
    dispatcher.callback_query.outer_middleware(tracking)
    dispatcher.include_router(
        build_studio_router(storage, admin_access, active_test_engines)
    )
    dispatcher.include_router(bot_app.router)

    host = os.getenv("BUILDER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("BUILDER_PORT", "8080"))
    studio = RoadmapStudioServer(
        root,
        bot,
        storage,
        admin_access,
        active_test_engines,
    )
    await studio.start(host, port)

    url = f"http://{host}:{port}/builder/"
    if os.getenv("BUILDER_OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no"}:
        with suppress(Exception):
            webbrowser.open(url)

    try:
        await dispatcher.start_polling(bot)
    finally:
        await studio.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
