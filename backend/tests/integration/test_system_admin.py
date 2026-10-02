"""Phase 12: the organizer's System page data. Versions, health, disk, addresses, the live event,
visits in progress and the last cleanup; nothing secret, and only for a signed-in organizer."""

from __future__ import annotations

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.modules.retention.domain import Trigger
from tests.integration.admin_support import adopt_device, device_headers
from tests.integration.test_booth_sessions import activate, booth, start


def test_the_system_page_tells_the_organizer_how_the_booth_is(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, name="Garden Party")
    start(kiosk_client, device)
    container.retention_service.run(Trigger.MANUAL, dry_run=False)

    answer = kiosk_client.get("/api/admin/system", headers=device)
    assert answer.status_code == 200, answer.text
    assert answer.headers["cache-control"] == "no-store"
    body = answer.json()
    assert body == body | {
        "instance": "dummy",
        "database": "ok",
        "active_event": "Garden Party",
        "visits_in_progress": 1,
        "schema_revision": "0011_retention",
        "last_cleanup_errors": [],
    }
    assert body["disk_total_bytes"] >= body["disk_free_bytes"] > 0
    assert body["storage_bytes"] >= 0
    assert body["last_cleanup_at"] is not None
    assert body["kiosk_url"].startswith("http://127.0.0.1:")
    assert body["delivery_url"].startswith("http://")

    # Nothing secret reaches the page.
    text = answer.text
    for secret in (
        container.launcher.path.read_text(encoding="utf-8")
        if container.launcher.path.exists()
        else "",
        str(container.settings.instance_root),
        str(container.settings.db_path),
    ):
        if secret:
            assert secret not in text


def test_the_system_page_needs_an_organizer(kiosk_client: TestClient, container: Container) -> None:
    device = device_headers(adopt_device(kiosk_client, container))
    assert kiosk_client.get("/api/admin/system", headers=device).status_code == 401
