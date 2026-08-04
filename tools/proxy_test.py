from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from app.config import load_settings
from app.telegram import build_bot


async def run(chat_id: int, text: str) -> None:
    settings = load_settings()
    bot = build_bot(settings)
    mode = "через PROXY_URL" if settings.proxy_url else "напрямую без прокси"
    try:
        me = await bot.get_me()
        await bot.send_message(
            chat_id,
            f"✅ Проверка соединения успешна\n"
            f"Бот: @{me.username}\n"
            f"Режим: {mode}\n"
            f"Текст: {text}\n"
            f"Время запуска: {datetime.now().isoformat(timespec='seconds')}",
        )
        print(f"OK: message sent {mode} to chat_id={chat_id}")
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one Telegram message using PROXY_URL from .env")
    parser.add_argument("--chat-id", type=int, required=True, help="Destination Telegram chat ID")
    parser.add_argument("--text", default="Тест прокси", help="Marker text")
    args = parser.parse_args()
    asyncio.run(run(args.chat_id, args.text))


if __name__ == "__main__":
    main()
