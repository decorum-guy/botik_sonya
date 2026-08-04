import asyncio

from app.admin_access import AdminAccess


def test_password_binds_only_one_admin(tmp_path) -> None:
    async def scenario() -> None:
        access = AdminAccess(tmp_path / "admin.db", "secret-value")
        await access.init()

        wrong = await access.authenticate(100, "wrong")
        assert not wrong.ok
        assert wrong.status == "wrong_password"

        first = await access.authenticate(100, "secret-value")
        assert first.ok
        assert first.status == "bound"
        assert await access.is_admin(100)

        second = await access.authenticate(200, "secret-value")
        assert not second.ok
        assert second.status == "already_bound"
        assert not await access.is_admin(200)

    asyncio.run(scenario())
