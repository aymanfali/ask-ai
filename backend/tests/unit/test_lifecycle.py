from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import ask_ai.main as main_module
from ask_ai.core.config import Settings
from ask_ai.database.session import get_db_session
from ask_ai.main import create_app


class FakeResult:
    @staticmethod
    def scalar_one() -> int:
        return 1


class FakeConnection:
    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _: object) -> FakeResult:
        return FakeResult()


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def connect(self) -> FakeConnection:
        return FakeConnection()

    async def dispose(self) -> None:
        self.disposed = True


class FakeSession:
    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _: object) -> FakeResult:
        return FakeResult()


class FakeSessionFactory:
    def __call__(self) -> FakeSession:
        return FakeSession()


class FakeRedis:
    def __init__(self) -> None:
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


def test_lifespan_owns_database_and_redis_resources(monkeypatch) -> None:
    settings = Settings(app_env="test")
    engine = FakeEngine()
    redis_client = FakeRedis()

    monkeypatch.setattr(main_module, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _: redis_client)
    monkeypatch.setattr(
        main_module,
        "async_sessionmaker",
        lambda **_: FakeSessionFactory(),
    )

    app = create_app(settings)

    @app.get("/test/database")
    async def database_probe(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, int]:
        result = await session.execute(text("SELECT 1"))
        return {"result": int(result.scalar_one())}

    with TestClient(app) as client:
        assert client.get("/test/database").json() == {"result": 1}
        readiness = client.get("/api/v1/health/ready")
        assert readiness.status_code == 200
        assert readiness.json() == {
            "status": "ready",
            "checks": {"database": "ok", "redis": "ok"},
        }

    assert redis_client.closed is True
    assert engine.disposed is True
