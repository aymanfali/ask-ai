from typing import Annotated

from fastapi import Body
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from ask_ai.core.config import Settings
from ask_ai.core.errors import ApplicationError
from ask_ai.main import create_app


class ShortPasswordPayload(BaseModel):
    password: str = Field(min_length=8)


def test_validation_error_uses_standard_envelope_without_echoing_input(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)

    @app.post("/test-validation")
    async def validate_payload(
        payload: Annotated[ShortPasswordPayload, Body()],
    ) -> dict[str, str]:
        return {"status": "accepted"}

    response = TestClient(app).post(
        "/test-validation",
        json={"password": "short"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["request_id"] == response.headers["x-request-id"]
    assert '"short"' not in response.text


def test_application_error_uses_standard_envelope(test_settings: Settings) -> None:
    app = create_app(test_settings)

    @app.get("/test-application-error")
    async def raise_error() -> None:
        raise ApplicationError(
            code="example_conflict",
            message="The example resource is unavailable.",
            status_code=409,
        )

    response = TestClient(app).get("/test-application-error")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "example_conflict"
