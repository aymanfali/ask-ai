import uuid

from fastapi.testclient import TestClient

from ask_ai.core.config import Settings
from ask_ai.main import create_app


def test_request_id_is_generated_and_returned(test_settings: Settings) -> None:
    response = TestClient(create_app(test_settings)).get("/api/v1/health/live")

    request_id = response.headers["x-request-id"]
    uuid.UUID(request_id)
    assert response.status_code == 200


def test_valid_client_request_id_is_preserved(test_settings: Settings) -> None:
    request_id = str(uuid.uuid4())
    response = TestClient(create_app(test_settings)).get(
        "/api/v1/health/live",
        headers={"X-Request-ID": request_id},
    )

    assert response.headers["x-request-id"] == request_id


def test_invalid_client_request_id_is_replaced(test_settings: Settings) -> None:
    response = TestClient(create_app(test_settings)).get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "not-a-uuid"},
    )

    assert response.headers["x-request-id"] != "not-a-uuid"
    uuid.UUID(response.headers["x-request-id"])
