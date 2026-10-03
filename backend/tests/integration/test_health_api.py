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
    assert body["schema_revision"] == "0012_policy_per_event"


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
        "/api/templates",
        "/api/templates/{key}",
        "/api/templates/{key}/blank.png",
        "/api/templates/{key}/guide.png",
        "/api/render/samples/{key}/{output_index}.jpg",
        "/api/admin/auth/login",
        "/api/admin/auth/session",
        "/api/admin/auth/logout",
        "/api/admin/assets",
        "/api/admin/assets/{asset_id}",
        "/api/admin/assets/{asset_id}/content",
        "/api/admin/profiles",
        "/api/admin/profiles/{profile_id}",
        "/api/admin/profiles/{profile_id}/duplicate",
        "/api/admin/profiles/{profile_id}/activate",
        "/api/admin/profiles/{profile_id}/restore",
        "/api/admin/frames",
        "/api/admin/frames/{frame_id}",
        "/api/admin/frames/{frame_id}/content",
        "/api/admin/frames/{frame_id}/preview/{output_index}.jpg",
        "/api/admin/frames/{frame_id}/replace",
        "/api/admin/frames/{frame_id}/name",
        "/api/admin/themes",
        "/api/admin/themes/extract",
        "/api/admin/themes/main-colours",
        "/api/booth/frames",
        "/api/booth/frames/{frame_id}/preview.jpg",
        "/api/booth/start/{kind}",
        "/api/admin/booth-test/cleanup",
        "/api/admin/booth-test/menu/{profile_id}",
        "/api/admin/booth-test/sessions",
        "/api/booth/sessions",
        "/api/booth/sessions/{session_id}/captures/{capture_id}.jpg",
        "/api/booth/sessions/current",
        "/api/booth/sessions/{session_id}",
        "/api/booth/sessions/{session_id}/captures",
        "/api/booth/sessions/{session_id}/finish",
        "/api/booth/sessions/{session_id}/frame",
        "/api/booth/sessions/{session_id}/give-up",
        "/api/booth/sessions/{session_id}/retake",
        "/api/booth/sessions/{session_id}/render",
        "/api/booth/sessions/{session_id}/outputs/{output_id}.jpg",
        "/api/booth/sessions/{session_id}/delivery",
        "/api/booth/sessions/{session_id}/decorate",
        "/api/booth/sessions/{session_id}/frame.png",
        "/api/booth/decorations",
        "/api/booth/decorations/stickers/{key}.png",
        "/api/admin/activity",
        "/api/admin/history",
        "/api/admin/history/{session_id}",
        "/api/admin/statistics",
        "/api/admin/retention/policies",
        "/api/admin/retention/policies/{policy_id}",
        "/api/admin/retention/policies/{policy_id}/default",
        "/api/admin/retention/housekeeping",
        "/api/admin/retention/run",
        "/api/admin/retention/runs",
        "/api/admin/retention/events/{profile_id}/remove",
        "/api/admin/system",
    }
