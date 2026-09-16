from __future__ import annotations

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.main import KioskAppOptions, create_kiosk_app


def test_health_contract(kiosk_client: TestClient) -> None:
    response = kiosk_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "instance": "dummy", "database": "ok"}


def test_version_contract(kiosk_client: TestClient) -> None:
    response = kiosk_client.get("/api/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"app_version", "api_version", "instance", "schema_revision", "git_commit"}
    assert body["app_version"] == "0.1.0"
    assert body["api_version"] == 1
    assert body["instance"] == "dummy"
    assert body["schema_revision"] == "0001_baseline"


def test_health_reports_database_error(container: Container) -> None:
    container.engine.dispose()
    container.settings.db_path.unlink()
    for suffix in ("-wal", "-shm"):
        container.settings.db_path.with_name(container.settings.db_path.name + suffix).unlink(
            missing_ok=True
        )
    app = create_kiosk_app(container.registry, KioskAppOptions())
    with TestClient(app, base_url="http://127.0.0.1:18111") as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["database"] == "error"


def test_openapi_lists_only_expected_public_paths(kiosk_client: TestClient) -> None:
    paths = set(kiosk_client.get("/api/openapi.json").json()["paths"])
    assert paths == {
        "/api/health",
        "/api/version",
        "/api/kiosk/status",
        "/kiosk/pairing-code/rotate",
        "/api/booth/ping",
    }
