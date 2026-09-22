"""Photo sizes offered by an Event Profile: every valid frame of a chosen size reaches the booth."""

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
MENU = "/api/booth/frames"
NO_SIZES = "No photo sizes are available to participants"
NO_FRAMES = "No frames exist for the chosen photo sizes"


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


def activate(client: TestClient, headers: dict[str, str], profile: dict[str, Any]) -> Any:
    return client.post(f"{PROFILES}/{profile['id']}/activate", headers=headers)


def menu_ids(client: TestClient) -> list[str]:
    return [frame["id"] for frame in client.get(MENU).json()["frames"]]


def test_a_new_profile_offers_every_size_and_so_every_frame_including_later_uploads(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    created = kiosk_client.post(PROFILES, json=body(), headers=headers)
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["settings"]["enabled_layouts"] == sorted(LAYOUTS)
    assert profile["settings"]["allow_surprise_me"] is False
    assert activate(kiosk_client, headers, profile).status_code == 200
    assert len(menu_ids(kiosk_client)) == len(FAMILIES) * len(LAYOUTS)

    # An upload made later is offered at once: no profile edit needed.
    _s, mine = upload(kiosk_client, headers, key="strip_2x6", name="Mine")
    assert mine["id"] in menu_ids(kiosk_client)
    reopened = kiosk_client.get(f"{PROFILES}/{profile['id']}").json()
    assert reopened["revision"] == profile["revision"]  # the profile itself never changed


def test_participants_get_every_valid_frame_of_the_chosen_sizes_in_a_stable_order(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, b = upload(kiosk_client, headers, key="strip_2x6", name="Beta strip")
    _s, a = upload(kiosk_client, headers, key="strip_2x6", name="Alpha strip")
    _s, other = upload(kiosk_client, headers, key="print_4x6", name="Big one")
    profile = kiosk_client.post(
        PROFILES, json=body(enabled_layouts=["strip_2x6", "print_3x4"]), headers=headers
    ).json()
    assert profile["settings"]["enabled_layouts"] == ["print_3x4", "strip_2x6"]  # catalogue order
    assert activate(kiosk_client, headers, profile).status_code == 200
    ids = menu_ids(kiosk_client)
    expected = [
        *(
            builtin_frame_id(f, "print_3x4")
            for f in ("celebration_gold", "midnight", "minimal_light")
        ),
        *(
            builtin_frame_id(f, "strip_2x6")
            for f in ("celebration_gold", "midnight", "minimal_light")
        ),
        a["id"],
        b["id"],
    ]
    assert ids == expected  # sizes in order; built-in frames first, then names A-Z
    assert other["id"] not in ids  # a size that is switched off offers nothing
    assert kiosk_client.get(MENU).json()["layouts"] == ["print_3x4", "strip_2x6"]

    # Renaming or replacing a frame shows up at once; deleting one removes it.
    renamed = kiosk_client.put(f"{FRAMES}/{b['id']}/name", json={"name": "Zeta"}, headers=headers)
    assert renamed.status_code == 200
    names = [f["name"] for f in kiosk_client.get(MENU).json()["frames"]]
    assert names[-1] == "Zeta"
    before = next(f for f in kiosk_client.get(MENU).json()["frames"] if f["id"] == a["id"])
    replaced = kiosk_client.post(
        f"{FRAMES}/{a['id']}/replace",
        files={
            "file": ("f.png", frame_png(TEMPLATES["strip_2x6"], fill=(9, 9, 9, 255)), "image/png")
        },
        headers=headers,
    )
    assert replaced.status_code == 200
    after = next(f for f in kiosk_client.get(MENU).json()["frames"] if f["id"] == a["id"])
    assert after["preview_url"] != before["preview_url"]  # new file, new preview
    deleted = kiosk_client.delete(f"{FRAMES}/{a['id']}", headers=headers)
    assert deleted.status_code == 204  # a size, not the frame, is what a profile offers
    assert a["id"] not in menu_ids(kiosk_client)
    assert (
        kiosk_client.post(
            "/api/booth/frame-choice", json={"frame_id": a["id"]}, headers=headers
        ).status_code
        == 404
    )

    # Switching a size off removes all its frames; on again brings them back.
    only_prints = put(kiosk_client, headers, profile, enabled_layouts=["print_3x4"])
    assert only_prints.status_code == 200, only_prints.text
    assert all(frame_id not in menu_ids(kiosk_client) for frame_id in expected[3:])


def test_refuses_repeats_unknown_sizes_and_an_edit_without_the_list(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    repeated = kiosk_client.post(
        PROFILES, json=body(enabled_layouts=["strip_2x6", "strip_2x6"]), headers=headers
    )
    assert repeated.status_code == 422 and "only once" in repeated.json()["detail"]
    unknown = kiosk_client.post(PROFILES, json=body(enabled_layouts=["poster_a4"]), headers=headers)
    assert unknown.status_code == 422 and "unknown photo sizes" in unknown.json()["detail"]
    assert kiosk_client.get(PROFILES).json() == []

    profile = kiosk_client.post(PROFILES, json=body(), headers=headers).json()
    without_list = {k: v for k, v in profile["settings"].items() if k != "enabled_layouts"}
    refused = kiosk_client.put(
        f"{PROFILES}/{profile['id']}",
        json={**without_list, "revision": profile["revision"]},
        headers=headers,
    )
    assert refused.status_code == 422  # an edit always states the full list


def test_activation_needs_a_size_and_a_valid_frame_of_it(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    empty = kiosk_client.post(PROFILES, json=body(enabled_layouts=[]), headers=headers).json()
    refused = activate(kiosk_client, headers, empty)
    assert refused.status_code == 409 and NO_SIZES in refused.json()["detail"]

    ready = kiosk_client.post(PROFILES, json=body(name="Ready"), headers=headers).json()
    active = activate(kiosk_client, headers, ready).json()
    assert active["is_active"] is True
    # The active profile can not lose its last size.
    emptied = put(kiosk_client, headers, active, enabled_layouts=[])
    assert emptied.status_code == 422 and NO_SIZES in emptied.json()["detail"]
    assert kiosk_client.get(f"{PROFILES}/{ready['id']}").json()["revision"] == active["revision"]


def test_activation_is_refused_when_no_valid_frame_exists_for_the_sizes(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    profile = kiosk_client.post(
        PROFILES, json=body(enabled_layouts=["print_3x4"]), headers=headers
    ).json()
    # No valid frame of that size (as if the built-in files were retired).
    service = container.frame_service
    original = service.offered_frames
    service.offered_frames = lambda layouts: []  # type: ignore[method-assign]
    try:
        refused = activate(kiosk_client, headers, profile)
    finally:
        service.offered_frames = original  # type: ignore[method-assign]
    assert refused.status_code == 409 and NO_FRAMES in refused.json()["detail"]
    assert activate(kiosk_client, headers, profile).status_code == 200


def test_frames_page_shows_which_profiles_offer_each_size(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, strip = upload(kiosk_client, headers, key="strip_2x6", name="Strip frame")
    created = kiosk_client.post(
        PROFILES, json=body(name="Wedding", enabled_layouts=["strip_2x6"]), headers=headers
    ).json()
    kiosk_client.post(
        PROFILES, json=body(name="Prints", enabled_layouts=["print_4x6"]), headers=headers
    )
    listed = {f["id"]: f for f in kiosk_client.get(FRAMES).json()}
    assert listed[strip["id"]]["used_by"] == ["Wedding"]
    assert listed[builtin_frame_id("midnight", "strip_2x6")]["used_by"] == ["Wedding"]
    assert listed[builtin_frame_id("midnight", "print_4x6")]["used_by"] == ["Prints"]
    assert listed[builtin_frame_id("midnight", "print_3x4")]["used_by"] == []
    # A soft-deleted profile is marked (it can be restored).
    kiosk_client.delete(f"{PROFILES}/{created['id']}?revision=1", headers=headers)
    assert kiosk_client.get(f"{FRAMES}/{strip['id']}").json()["used_by"] == ["Wedding (deleted)"]


def test_stale_revision_changes_no_sizes(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    profile = kiosk_client.post(
        PROFILES, json=body(enabled_layouts=["strip_2x6"]), headers=headers
    ).json()
    assert put(kiosk_client, headers, profile, enabled_layouts=["print_4x6"]).status_code == 200
    stale = put(kiosk_client, headers, profile, enabled_layouts=["print_3x4"])
    assert stale.status_code == 409
    current = kiosk_client.get(f"{PROFILES}/{profile['id']}").json()
    assert current["settings"]["enabled_layouts"] == ["print_4x6"]


def test_duplicate_copies_sizes_surprise_and_countdown(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    profile = kiosk_client.post(
        PROFILES,
        json=body(
            enabled_layouts=["print_3x4", "strip_2x6"], allow_surprise_me=True, countdown_seconds=7
        ),
        headers=headers,
    ).json()
    copy = kiosk_client.post(
        f"{PROFILES}/{profile['id']}/duplicate", json={}, headers=headers
    ).json()
    assert copy["settings"]["enabled_layouts"] == ["print_3x4", "strip_2x6"]
    assert copy["settings"]["allow_surprise_me"] is True
    assert copy["settings"]["countdown_seconds"] == 7


def test_sizes_and_dynamic_frames_survive_a_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, first)
            profile = client.post(
                PROFILES,
                json=body(enabled_layouts=["print_4x6"], allow_surprise_me=True),
                headers=headers,
            ).json()
            activate(client, headers, profile)
    finally:
        first.close()

    second = Container(settings)
    try:
        app = create_kiosk_app(second.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, second, create_user=False)
            reloaded = client.get(f"{PROFILES}/{profile['id']}").json()
            assert reloaded["settings"]["enabled_layouts"] == ["print_4x6"]
            _s, frame = upload(client, headers, key="print_4x6", name="After restart")
            assert frame["id"] in menu_ids(client)
    finally:
        second.close()
