import os
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.core.config import Settings
from ask_ai.database.session import get_db_session
from ask_ai.main import create_app


@pytest.mark.integration
def test_real_application_lifecycle_and_session_dependency() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    redis_url = os.getenv("TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required")

    settings = Settings(
        app_env="test",
        database_url=database_url,
        redis_url=redis_url,
    )
    app = create_app(settings)

    @app.get("/test/infrastructure")
    async def infrastructure_probe(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, int]:
        result = await session.execute(text("SELECT 1"))
        return {"result": int(result.scalar_one())}

    with TestClient(app) as client:
        response = client.get("/test/infrastructure")
        assert response.status_code == 200
        assert response.json() == {"result": 1}
        readiness = client.get("/api/v1/health/ready")
        assert readiness.status_code == 200
        assert readiness.json() == {
            "status": "ready",
            "checks": {"database": "ok", "redis": "ok"},
        }
