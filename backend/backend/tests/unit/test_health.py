import pytest
from fastapi.testclient import TestClient

from ask_ai.core.config import Settings
from ask_ai.main import create_app


@pytest.mark.parametrize("path", ["/api/v1/health/live"])
def test_liveness_returns_ok(test_settings: Settings, path: str) -> None:
    response = TestClient(create_app(test_settings)).get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_not_ready_when_dependencies_fail(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ask_ai.api.v1.endpoints import health

    async def unavailable_database(_: object) -> bool:
        return False

    async def unavailable_redis(_: object) -> bool:
        return False

    monkeypatch.setattr(health, "_database_probe", unavailable_database)
    monkeypatch.setattr(health, "_redis_probe", unavailable_redis)

    response = TestClient(create_app(test_settings)).get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable", "redis": "unavailable"},
    }
