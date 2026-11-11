from typing import Annotated

import structlog
from fastapi import Body
from fastapi.testclient import TestClient

from store_operator.main import app
from store_operator.observability import configure_logging

@app.post("/_test/validation")
def validation_probe(quantity: Annotated[int, Body()]) -> dict[str, int]:
    return {"quantity": quantity}


client = TestClient(app)


def test_liveness_is_independent_of_external_services():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_system_info_exposes_api_version():
    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"


def test_health_response_includes_request_id() -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "test-request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"


def test_structured_logging_redacts_nested_secrets(capsys) -> None:
    configure_logging()
    logger = structlog.get_logger("test.redaction")
    logger.info(
        "auth.request",
        request_id="req-123",
        password="plain-secret",
        nested={"api_key": "api-secret", "safe": "visible"},
    )

    output = capsys.readouterr().out
    assert "plain-secret" not in output
    assert "api-secret" not in output
    assert "[REDACTED]" in output
    assert "req-123" in output
    assert "visible" in output



def test_not_found_uses_unified_error_envelope() -> None:
    response = client.get("/_missing")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "Resource not found",
    }
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_uses_unified_envelope_without_echoing_input() -> None:
    response = client.post("/_test/validation", json="sensitive-invalid-input")

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed",
    }
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "sensitive-invalid-input" not in response.text
