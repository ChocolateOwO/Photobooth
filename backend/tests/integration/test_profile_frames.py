"""Per-layout frame selection in Event Profiles, and frame deletion while still referenced."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from tests.integration.admin_support import login
from tests.integration.test_frames_api import TEMPLATES, upload
from tests.unit.test_frame_validator import frame_png

PROFILES = "/api/admin/profiles"
FRAMES = "/api/admin/frames"


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "name": "Expo",
        "title": "Welcome",
        "enabled_layouts": ["strip_2x6", "print_4x6"],
    }
    values.update(overrides)
    return values


def test_choose_a_frame_per_enabled_layout(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    _s, strip = upload(kiosk_client, headers, key="strip_2x6", name="Strip frame")
    _s, print46 = upload(kiosk_client, headers, key="print_4x6", name="Print frame")

    created = kiosk_client.post(PROFILES, json=body(), headers=headers)
    assert created.status_code == 201, created.text
    profile = created.json()
    # A new profile has no frames yet: every enabled layout is unselected.
    assert profile["settings"]["frame_selections"] == {}

    chosen = {"strip_2x6": strip["id"], "print_4x6": print46["id"]}
    updated = kiosk_client.put(
        f"{PROFILES}/{profile['id']}",
        json={**body(frame_selections=chosen), "revision": profile["revision"]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["settings"]["frame_selections"] == chosen

    reopened = kiosk_client.get(f"{PROFILES}/{profile['id']}").json()
    assert reopened["settings"]["frame_selections"] == chosen

    # Choosing a frame for only one layout is allowed (the other stays unselected).
    one = kiosk_client.put(
        f"{PROFILES}/{profile['id']}",
        json={
            **body(frame_selections={"strip_2x6": strip["id"]}),
            "revision": reopened["revision"],
        },
        headers=headers,
    )
    assert one.status_code == 200
    assert one.json()["settings"]["frame_selections"] == {"strip_2x6": strip["id"]}


def test_refuses_frames_from_another_layout_or_unknown_frames(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, strip = upload(kiosk_client, headers, key="strip_2x6", name="Strip frame")
    missing = "00000000-0000-4000-8000-000000000000"

    wrong_layout = kiosk_client.post(
        PROFILES, json=body(frame_selections={"print_4x6": strip["id"]}), headers=headers
    )
    assert wrong_layout.status_code == 422
    assert "belongs to the strip_2x6 layout" in wrong_layout.json()["detail"]

    unknown = kiosk_client.post(
        PROFILES, json=body(frame_selections={"strip_2x6": missing}), headers=headers
    )
    assert unknown.status_code == 422 and "does not exist" in unknown.json()["detail"]

    not_enabled = kiosk_client.post(
        PROFILES,
        json=body(enabled_layouts=["print_4x6"], frame_selections={"strip_2x6": strip["id"]}),
        headers=headers,
    )
    assert not_enabled.status_code == 422
    assert "layouts that are not enabled" in not_enabled.json()["detail"]
    assert kiosk_client.get(PROFILES).json() == []


def test_disabling_a_layout_requires_dropping_its_frame_selection(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, strip = upload(kiosk_client, headers, key="strip_2x6", name="Strip frame")
    created = kiosk_client.post(
        PROFILES, json=body(frame_selections={"strip_2x6": strip["id"]}), headers=headers
    ).json()
    # Keeping a frame for a layout that is switched off is refused, not silently dropped.
    stale = kiosk_client.put(
        f"{PROFILES}/{created['id']}",
        json={
            **body(enabled_layouts=["print_4x6"], frame_selections={"strip_2x6": strip["id"]}),
            "revision": created["revision"],
        },
        headers=headers,
    )
    assert stale.status_code == 422
    assert "layouts that are not enabled" in stale.json()["detail"]

    updated = kiosk_client.put(
        f"{PROFILES}/{created['id']}",
        json={**body(enabled_layouts=["print_4x6"]), "revision": created["revision"]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["settings"]["frame_selections"] == {}
    # The frame is now unused, so it can be deleted.
    assert kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers).status_code == 204


def test_a_frame_in_use_can_not_be_deleted_but_can_be_replaced(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, strip = upload(kiosk_client, headers, key="strip_2x6", name="Strip frame")
    created = kiosk_client.post(
        PROFILES,
        json=body(name="Wedding", frame_selections={"strip_2x6": strip["id"]}),
        headers=headers,
    ).json()

    refused = kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers)
    assert refused.status_code == 409
    assert "Wedding" in refused.json()["detail"]
    assert kiosk_client.get(f"{FRAMES}/{strip['id']}").status_code == 200

    # The safe replacement flow: swap the file, keep the selection.
    replacement = frame_png(TEMPLATES["strip_2x6"], fill=(9, 9, 9, 255))
    replaced = kiosk_client.post(
        f"{FRAMES}/{strip['id']}/replace",
        files={"file": ("f.png", replacement, "image/png")},
        headers=headers,
    )
    assert replaced.status_code == 200
    assert kiosk_client.get(f"{FRAMES}/{strip['id']}/content").content == replacement
    still = kiosk_client.get(f"{PROFILES}/{created['id']}").json()
    assert still["settings"]["frame_selections"] == {"strip_2x6": strip["id"]}

    # A soft-deleted profile still holds its frame, because it can be restored.
    deleted = kiosk_client.delete(
        f"{PROFILES}/{created['id']}?revision={still['revision']}", headers=headers
    )
    assert deleted.status_code == 200
    still_refused = kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers)
    assert still_refused.status_code == 409
    assert "Wedding (deleted)" in still_refused.json()["detail"]

    # Clearing the selection on the restored profile releases the frame.
    restored = kiosk_client.post(f"{PROFILES}/{created['id']}/restore", headers=headers).json()
    cleared = kiosk_client.put(
        f"{PROFILES}/{created['id']}",
        json={**body(name="Wedding"), "revision": restored["revision"]},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers).status_code == 204


def test_stale_revision_does_not_change_frame_selection(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, first = upload(kiosk_client, headers, key="strip_2x6", name="First")
    _s, second = upload(kiosk_client, headers, key="strip_2x6", name="Second")
    created = kiosk_client.post(
        PROFILES, json=body(frame_selections={"strip_2x6": first["id"]}), headers=headers
    ).json()
    assert (
        kiosk_client.put(
            f"{PROFILES}/{created['id']}",
            json={**body(frame_selections={"strip_2x6": second["id"]}), "revision": 1},
            headers=headers,
        ).status_code
        == 200
    )
    stale = kiosk_client.put(
        f"{PROFILES}/{created['id']}",
        json={**body(frame_selections={"strip_2x6": first["id"]}), "revision": 1},
        headers=headers,
    )
    assert stale.status_code == 409
    current = kiosk_client.get(f"{PROFILES}/{created['id']}").json()
    assert current["settings"]["frame_selections"] == {"strip_2x6": second["id"]}


def test_frame_selection_survives_a_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, first)
            _s, frame = upload(client, headers, key="print_4x6", name="Persisted")
            profile = client.post(
                PROFILES,
                json=body(
                    enabled_layouts=["print_4x6"], frame_selections={"print_4x6": frame["id"]}
                ),
                headers=headers,
            ).json()
    finally:
        first.close()

    second = Container(settings)
    try:
        app = create_kiosk_app(second.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, second, create_user=False)
            reloaded = client.get(f"{PROFILES}/{profile['id']}").json()
            assert reloaded["settings"]["frame_selections"] == {"print_4x6": frame["id"]}
            assert client.delete(f"{FRAMES}/{frame['id']}", headers=headers).status_code == 409
    finally:
        second.close()
