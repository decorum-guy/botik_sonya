from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramNetworkError

import app.media_retry as media_retry


def test_media_delivery_retries_transient_network_errors(monkeypatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(media_retry.asyncio, "sleep", fake_sleep)

    class FakeEngine:
        calls = 0

        async def _send_media(self, chat_id: int, action) -> None:
            self.calls += 1
            if self.calls < 3:
                raise TelegramNetworkError(
                    method=SimpleNamespace(__api_method__="sendVideo"),
                    message="Request timeout error",
                )

    module = SimpleNamespace(QuestEngine=FakeEngine)
    media_retry.install_media_retry(module)
    engine = FakeEngine()

    asyncio.run(
        engine._send_media(
            123,
            SimpleNamespace(type="send_video"),
        )
    )

    assert engine.calls == 3
    assert sleeps == [2.0, 5.0]


def test_media_delivery_does_not_retry_permanent_errors(monkeypatch) -> None:
    async def fail_if_called(delay: float) -> None:  # pragma: no cover - safety assertion
        raise AssertionError(f"unexpected retry sleep: {delay}")

    monkeypatch.setattr(media_retry.asyncio, "sleep", fail_if_called)

    class FakeEngine:
        calls = 0

        async def _send_media(self, chat_id: int, action) -> None:
            self.calls += 1
            raise FileNotFoundError("missing media")

    module = SimpleNamespace(QuestEngine=FakeEngine)
    media_retry.install_media_retry(module)
    engine = FakeEngine()

    with pytest.raises(FileNotFoundError, match="missing media"):
        asyncio.run(
            engine._send_media(
                123,
                SimpleNamespace(type="send_photo"),
            )
        )

    assert engine.calls == 1


def test_network_retry_delay_is_capped() -> None:
    assert media_retry._network_retry_delay(1) == 2.0
    assert media_retry._network_retry_delay(2) == 5.0
    assert media_retry._network_retry_delay(999) == 60.0
