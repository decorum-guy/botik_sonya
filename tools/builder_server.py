from __future__ import annotations

import asyncio
import logging
import os
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Dispatcher
from dotenv import load_dotenv
from pydantic import ValidationError

import app.main as bot_app
from app.admin_access import AdminAccess
from app.builder_api import BuilderApiError, prepare_test_roadmap
from app.config import load_settings
from app.engine import QuestEngine
from app.memory_variables import collect_memory_variables
from app.models import Roadmap
from app.roadmap import load_roadmap
from app.storage import Storage
from app.telegram import build_bot

logger = logging.getLogger(__name__)


class RoadmapStudioServer:
    def __init__(self, root: Path, bot, storage: Storage) -> None:
        self.root = root.resolve()
        self.builder_dir = (self.root / "builder").resolve()
        self.bot = bot
        self.storage = storage
        self.runner: web.AppRunner | None = None

    async def start(self, host: str, port: int) -> None:
        application = web.Application(client_max_size=8 * 1024 * 1024)
        application.router.add_get("/", self._redirect)
        application.router.add_get("/builder", self._redirect)
        application.router.add_get("/builder/", self._index)
        application.router.add_get("/api/test-status", self._status)
        application.router.add_post("/api/test-run", self._run)
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

    async def _status(self, request: web.Request) -> web.Response:
        participant = await self.storage.participant_chat_id()
        return web.json_response(
            {
                "ok": True,
                "participant_available": participant is not None,
                "participant_chat_id": participant,
            }
        )

    async def _run(self, request: web.Request) -> web.Response:
        try:
            payload: dict[str, Any] = await request.json()
            roadmap = Roadmap.model_validate(payload.get("roadmap"))
            scope = str(payload.get("scope") or "full")
            step_id_value = payload.get("step_id")
            step_id = str(step_id_value) if step_id_value is not None else None
            action_index_value = payload.get("action_index")
            action_index = int(action_index_value) if action_index_value is not None else None

            participant = await self.storage.participant_chat_id()
            if participant is None:
                raise BuilderApiError(
                    "Тестовый аккаунт не привязан. Запусти этот сервер, затем отправь боту /start "
                    "со второго Telegram-аккаунта."
                )

            test_roadmap, start_step_id = prepare_test_roadmap(
                roadmap,
                scope,
                step_id=step_id,
                action_index=action_index,
            )
            test_engine = QuestEngine(self.bot, self.storage, test_roadmap, self.root)

            # The normal Telegram handlers in app.main refer to this global
            # engine. Replacing it here keeps replies and inline buttons working
            # after a live roadmap has been launched from the editor.
            bot_app.engine = test_engine
            await test_engine.start(participant, start_step_id)
        except BuilderApiError as exc:
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
                "message": f"{labels.get(scope, 'Сценарий запущен')} в тестовом аккаунте.",
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

    dispatcher = Dispatcher()
    dispatcher.include_router(bot_app.router)

    host = os.getenv("BUILDER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("BUILDER_PORT", "8080"))
    studio = RoadmapStudioServer(root, bot, storage)
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
