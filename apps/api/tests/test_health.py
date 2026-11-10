from fastapi.testclient import TestClient

from store_operator.main import app

client = TestClient(app)


def test_liveness_does_not_depend_on_external_services() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_system_info_exposes_api_version() -> None:
    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
