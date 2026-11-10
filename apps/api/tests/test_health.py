from fastapi.testclient import TestClient

from store_operator.main import app

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
