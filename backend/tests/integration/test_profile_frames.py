"""Frames offered to participants by an Event Profile: ordered, many per layout, safe to delete."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.frames.builtin import FAMILIES, LAYOUTS, builtin_frame_id
from tests.integration.admin_support import login
from tests.integration.test_frames_api import TEMPLATES, upload
from tests.unit.test_frame_validator import frame_png

PROFILES = "/api/admin/profiles"
FRAMES = "/api/admin/frames"
NO_FRAMES = "No frames are available to participants"


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"name": "Expo", "title": "Welcome"}
    values.update(overrides)
    return values


def put(
    client: TestClient, headers: dict[str, str], profile: dict[str, Any], **changes: Any
) -> Any:
    settings = {**profile["settings"], **changes}
    return client.put(
        f"{PROFILES}/{profile['id']}",
        json={**settings, "revision": profile["revision"]},
        headers=headers,
    )


def test_a_new_profile_offers_every_builtin_frame_but_never_later_uploads(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    created = kiosk_client.post(PROFILES, json=body(), headers=headers)
    assert created.status_code == 201, created.text
    profile = created.json()
    builtin_ids = [f["id"] for f in kiosk_client.get(FRAMES).json() if f["builtin"]]
    assert profile["settings"]["available_frames"] == builtin_ids
    assert len(builtin_ids) == len(FAMILIES) * len(LAYOUTS)
    assert sorted(profile["available_layouts"]) == sorted(LAYOUTS)
    assert profile["settings"]["allow_surprise_me"] is False

    _s, mine = upload(kiosk_client, headers, key="strip_2x6", name="Mine")
    reopened = kiosk_client.get(f"{PROFILES}/{profile['id']}").json()
    assert mine["id"] not in reopened["settings"]["available_frames"]
    assert reopened["settings"]["available_frames"] == builtin_ids


def test_many_frames_per_layout_in_a_saved_order_and_derived_layouts(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, a = upload(kiosk_client, headers, key="strip_2x6", name="Strip A")
    _s, b = upload(kiosk_client, headers, key="strip_2x6", name="Strip B")
    gold46 = builtin_frame_id("celebration_gold", "print_4x6")
    order = [b["id"], gold46, a["id"]]
    profile = kiosk_client.post(
        PROFILES, json=body(available_frames=order, allow_surprise_me=True), headers=headers
    ).json()
    assert profile["settings"]["available_frames"] == order
    assert profile["available_layouts"] == ["strip_2x6", "print_4x6"]  # first-use order
    assert profile["settings"]["allow_surprise_me"] is True

    # Reordering replaces the whole list at once.
    reordered = put(kiosk_client, headers, profile, available_frames=[a["id"], b["id"], gold46])
    assert reordered.status_code == 200, reordered.text
    assert reordered.json()["settings"]["available_frames"] == [a["id"], b["id"], gold46]

    # Switching off the last 4x6 frame removes the 4x6 layout from the participants' choices.
    without_46 = put(kiosk_client, headers, reordered.json(), available_frames=[a["id"], b["id"]])
    assert without_46.json()["available_layouts"] == ["strip_2x6"]
    # ...and switching one on brings its layout back.
    back = put(
        kiosk_client,
        headers,
        without_46.json(),
        available_frames=[a["id"], builtin_frame_id("midnight", "print_3x4"), b["id"]],
    )
    assert back.json()["available_layouts"] == ["strip_2x6", "print_3x4"]


def test_refuses_repeats_unknown_frames_and_an_edit_without_the_list(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    frame = builtin_frame_id("midnight", "strip_2x6")
    repeated = kiosk_client.post(
        PROFILES, json=body(available_frames=[frame, frame]), headers=headers
    )
    assert repeated.status_code == 422 and "only once" in repeated.json()["detail"]
    missing = "00000000-0000-4000-8000-000000000000"
    unknown = kiosk_client.post(PROFILES, json=body(available_frames=[missing]), headers=headers)
    assert unknown.status_code == 422 and "does not exist" in unknown.json()["detail"]
    assert kiosk_client.get(PROFILES).json() == []

    profile = kiosk_client.post(PROFILES, json=body(), headers=headers).json()
    without_list = {k: v for k, v in profile["settings"].items() if k != "available_frames"}
    refused = kiosk_client.put(
        f"{PROFILES}/{profile['id']}",
        json={**without_list, "revision": profile["revision"]},
        headers=headers,
    )
    assert refused.status_code == 422  # an edit always states the full list


def test_activation_needs_at_least_one_frame(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    empty = kiosk_client.post(PROFILES, json=body(available_frames=[]), headers=headers).json()
    assert empty["available_layouts"] == []
    refused = kiosk_client.post(f"{PROFILES}/{empty['id']}/activate", headers=headers)
    assert refused.status_code == 409 and NO_FRAMES in refused.json()["detail"]

    ready = kiosk_client.post(PROFILES, json=body(name="Ready"), headers=headers).json()
    active = kiosk_client.post(f"{PROFILES}/{ready['id']}/activate", headers=headers).json()
    assert active["is_active"] is True
    # The active profile can not lose its last frame.
    emptied = put(kiosk_client, headers, active, available_frames=[])
    assert emptied.status_code == 422 and NO_FRAMES in emptied.json()["detail"]
    assert kiosk_client.get(f"{PROFILES}/{ready['id']}").json()["revision"] == active["revision"]


def test_offered_frames_are_protected_and_shown_as_used(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, strip = upload(kiosk_client, headers, key="strip_2x6", name="Strip frame")
    created = kiosk_client.post(
        PROFILES, json=body(name="Wedding", available_frames=[strip["id"]]), headers=headers
    ).json()
    listed = {f["id"]: f for f in kiosk_client.get(FRAMES).json()}
    assert listed[strip["id"]]["used_by"] == ["Wedding"]
    assert kiosk_client.get(f"{FRAMES}/{strip['id']}").json()["used_by"] == ["Wedding"]

    refused = kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers)
    assert refused.status_code == 409 and "Wedding" in refused.json()["detail"]

    # Replacing the file keeps it offered.
    replacement = frame_png(TEMPLATES["strip_2x6"], fill=(9, 9, 9, 255))
    replaced = kiosk_client.post(
        f"{FRAMES}/{strip['id']}/replace",
        files={"file": ("f.png", replacement, "image/png")},
        headers=headers,
    )
    assert replaced.status_code == 200
    still = kiosk_client.get(f"{PROFILES}/{created['id']}").json()
    assert still["settings"]["available_frames"] == [strip["id"]]

    # A soft-deleted profile still holds its frames (it can be restored).
    deleted = kiosk_client.delete(
        f"{PROFILES}/{created['id']}?revision={still['revision']}", headers=headers
    )
    assert deleted.status_code == 200
    still_refused = kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers)
    assert "Wedding (deleted)" in still_refused.json()["detail"]
    restored = kiosk_client.post(f"{PROFILES}/{created['id']}/restore", headers=headers).json()
    assert restored["settings"]["available_frames"] == [strip["id"]]
    cleared = put(kiosk_client, headers, restored, available_frames=[])
    assert cleared.status_code == 200
    assert kiosk_client.delete(f"{FRAMES}/{strip['id']}", headers=headers).status_code == 204


def test_stale_revision_changes_neither_membership_nor_order(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    a = builtin_frame_id("midnight", "strip_2x6")
    b = builtin_frame_id("minimal_light", "strip_2x6")
    profile = kiosk_client.post(
        PROFILES, json=body(available_frames=[a, b]), headers=headers
    ).json()
    assert put(kiosk_client, headers, profile, available_frames=[b, a]).status_code == 200
    stale = put(kiosk_client, headers, profile, available_frames=[a])
    assert stale.status_code == 409
    current = kiosk_client.get(f"{PROFILES}/{profile['id']}").json()
    assert current["settings"]["available_frames"] == [b, a]


def test_duplicate_copies_frames_order_and_surprise(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    order = [
        builtin_frame_id("celebration_gold", "print_3x4"),
        builtin_frame_id("midnight", "strip_2x6"),
    ]
    profile = kiosk_client.post(
        PROFILES, json=body(available_frames=order, allow_surprise_me=True), headers=headers
    ).json()
    copy = kiosk_client.post(
        f"{PROFILES}/{profile['id']}/duplicate", json={}, headers=headers
    ).json()
    assert copy["settings"]["available_frames"] == order
    assert copy["settings"]["allow_surprise_me"] is True
    assert copy["available_layouts"] == ["print_3x4", "strip_2x6"]


def test_offered_frames_survive_a_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, first)
            _s, frame = upload(client, headers, key="print_4x6", name="Persisted")
            order = [frame["id"], builtin_frame_id("midnight", "print_4x6")]
            profile = client.post(
                PROFILES, json=body(available_frames=order, allow_surprise_me=True), headers=headers
            ).json()
    finally:
        first.close()

    second = Container(settings)
    try:
        app = create_kiosk_app(second.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, second, create_user=False)
            reloaded = client.get(f"{PROFILES}/{profile['id']}").json()
            assert reloaded["settings"]["available_frames"] == order
            assert reloaded["settings"]["allow_surprise_me"] is True
            assert client.delete(f"{FRAMES}/{frame['id']}", headers=headers).status_code == 409
    finally:
        second.close()
