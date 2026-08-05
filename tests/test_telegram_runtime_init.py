from __future__ import annotations

from types import SimpleNamespace

import app.telegram as telegram


def test_runtime_handlers_do_not_require_app_storage(monkeypatch) -> None:
    calls: list[tuple[str, object | None]] = []
    router = object()
    bot_app = SimpleNamespace(router=router)

    monkeypatch.setattr(
        telegram,
        "install_admin_ping",
        lambda installed_router: calls.append(("ping", installed_router)),
    )
    monkeypatch.setattr(
        telegram,
        "install_memory_debug",
        lambda installed_router: calls.append(("debug", installed_router)),
    )
    monkeypatch.setattr(
        telegram,
        "install_memory_batch_preview",
        lambda installed_router: calls.append(("batch", installed_router)),
    )
    monkeypatch.setattr(
        telegram,
        "install_memory_capture",
        lambda installed_router, storage: calls.append(("capture", storage)),
    )

    telegram._install_runtime_handlers(bot_app)

    assert calls == [
        ("ping", router),
        ("debug", router),
        ("batch", router),
    ]


def test_runtime_handlers_use_explicit_storage(monkeypatch) -> None:
    calls: list[tuple[str, object | None]] = []
    router = object()
    storage = object()
    bot_app = SimpleNamespace(router=router)

    monkeypatch.setattr(
        telegram,
        "install_admin_ping",
        lambda installed_router: calls.append(("ping", installed_router)),
    )
    monkeypatch.setattr(
        telegram,
        "install_memory_debug",
        lambda installed_router: calls.append(("debug", installed_router)),
    )
    monkeypatch.setattr(
        telegram,
        "install_memory_batch_preview",
        lambda installed_router: calls.append(("batch", installed_router)),
    )
    monkeypatch.setattr(
        telegram,
        "install_memory_capture",
        lambda installed_router, installed_storage: calls.append(
            ("capture", installed_storage)
        ),
    )

    telegram._install_runtime_handlers(bot_app, storage)

    assert calls == [
        ("ping", router),
        ("debug", router),
        ("batch", router),
        ("capture", storage),
    ]
