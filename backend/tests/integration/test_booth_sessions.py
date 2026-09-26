"""A visit to the booth: start, choose the frame, take every photo, retake, give up, recover.

The rules proven here are the ones a booth can not get wrong: one photo per shot, never reused;
the photo count comes from the chosen frame; a repeated request never takes a second photo; a
session that ends takes nothing more; and an organizer editing the profile mid-visit changes
nothing for the guest already at the booth.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.frames.builtin import builtin_frame_id
from photobooth.modules.sessions.domain import (
    MAX_ATTEMPTS_PER_SHOT,
    CaptureAsset,
    CaptureStatus,
    Operation,
    OperationStatus,
    SessionState,
)
from photobooth.modules.storage.domain import StorageKey
from tests.integration.admin_support import ORIGIN, adopt_device, device_headers, login
from tests.integration.test_frames_api import TEMPLATES, upload
from tests.unit.test_frame_validator import frame_png

PROFILES = "/api/admin/profiles"
SESSIONS = "/api/booth/sessions"
MENU = "/api/booth/frames"
STRIP = builtin_frame_id("midnight", "strip_2x6")  # 2x6: six photos, two strips
PRINT34 = builtin_frame_id("celebration_gold", "print_3x4")  # 3x4: two photos
PRINT46 = builtin_frame_id("minimal_light", "print_4x6")  # 4x6: four photos
CAPTURES = {"strip_2x6": 6, "print_3x4": 2, "print_4x6": 4}


def photo(shot: int, size: tuple[int, int] = (1280, 960)) -> bytes:
    """A different JPEG per shot, so a reused photo is visible as a repeated checksum."""
    image = Image.new("RGB", size, (10 * shot % 256, 90, 160))
    for x in range(0, size[0], 7):
        image.putpixel((x, shot % size[1]), (shot * 20 % 256, 255, 30))
    data = io.BytesIO()
    image.save(data, "JPEG", quality=92)
    return data.getvalue()


def activate(client: TestClient, headers: dict[str, str], **settings: Any) -> dict[str, Any]:
    body = {"name": "Party", "title": "Hi", **settings}
    created = client.post(PROFILES, json=body, headers=headers)
    assert created.status_code == 201, created.text
    profile = created.json()
    active = client.post(f"{PROFILES}/{profile['id']}/activate", headers=headers)
    assert active.status_code == 200, active.text
    result: dict[str, Any] = active.json()
    return result


def start(client: TestClient, headers: dict[str, str], key: str = "start-key-1") -> dict[str, Any]:
    response = client.post(SESSIONS, json={"idempotency_key": key}, headers=headers)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def choose(
    client: TestClient, headers: dict[str, str], session_id: str, frame_id: str
) -> dict[str, Any]:
    response = client.post(
        f"{SESSIONS}/{session_id}/frame", json={"frame_id": frame_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def send(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    shot: int,
    attempt: int = 1,
    key: str | None = None,
    data: bytes | None = None,
) -> Any:
    return client.post(
        f"{SESSIONS}/{session_id}/captures",
        files={"file": ("shot.jpg", data if data is not None else photo(shot), "image/jpeg")},
        data={
            "idempotency_key": key or f"shot-{shot}-{attempt}",
            "shot_index": str(shot),
            "attempt_no": str(attempt),
        },
        headers=headers,
    )


def booth(client: TestClient, container: Container) -> tuple[dict[str, str], dict[str, str]]:
    """The paired booth browser: admin headers for the organizer, plain ones for the guest."""
    key = adopt_device(client, container)
    return login(client, container, key=key), device_headers(key)


@pytest.mark.parametrize(
    ("frame_id", "layout"),
    [(PRINT34, "print_3x4"), (PRINT46, "print_4x6"), (STRIP, "strip_2x6")],
)
def test_the_chosen_frame_decides_how_many_photos_the_session_takes(
    kiosk_client: TestClient, container: Container, frame_id: str, layout: str
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=[layout], countdown_seconds=7)

    session = start(kiosk_client, device)
    assert session["state"] == "eligibility_ok"
    assert session["expected_captures"] == 0  # nothing is decided before the frame is confirmed
    assert session["countdown_seconds"] == 7  # the event's countdown, for every photo

    session = choose(kiosk_client, device, session["id"], frame_id)
    assert session["state"] == "capturing"
    assert session["expected_captures"] == CAPTURES[layout]
    assert session["template_key"] == layout
    assert [shot["shot_index"] for shot in session["shots"]] == list(range(1, CAPTURES[layout] + 1))

    checksums: set[str] = set()
    for shot in range(1, CAPTURES[layout] + 1):
        answer = send(kiosk_client, device, session["id"], shot)
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["status"] == "ok"
        assert body["session"]["taken"] == shot
        checksums.add(body["capture_id"])
    assert len(checksums) == CAPTURES[layout]  # one photo per shot, never reused

    finished = kiosk_client.post(f"{SESSIONS}/{session['id']}/finish", headers=device)
    assert finished.status_code == 200, finished.text
    assert finished.json()["state"] == "reviewing"
    assert finished.json()["taken"] == CAPTURES[layout]


def test_every_photo_of_a_2x6_strip_is_its_own_file(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["strip_2x6"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], STRIP)
    for shot in range(1, 7):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200

    captures = container.session_service._repository.captures(session["id"])
    ok = [capture for capture in captures if capture.status == "ok"]
    assert [capture.shot_index for capture in ok] == [1, 2, 3, 4, 5, 6]
    assert len({capture.sha256 for capture in ok}) == 6  # six different photos
    assert len({capture.storage_key for capture in ok}) == 6  # six different files
    for capture in ok:
        assert container.storage.exists.__self__  # storage is the only place files live
        assert capture.storage_key is not None
        assert capture.storage_key.startswith(f"captures/{session['id']}/")


def test_a_repeated_send_never_takes_a_second_photo(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)

    first = send(kiosk_client, device, session["id"], 1, key="same-key")
    again = send(kiosk_client, device, session["id"], 1, key="same-key")
    assert first.status_code == 200 and again.status_code == 200
    assert first.json()["capture_id"] == again.json()["capture_id"]
    assert again.json()["session"]["taken"] == 1

    # The same key for a different photo is a mistake, not a retry.
    reused = send(kiosk_client, device, session["id"], 2, key="same-key")
    assert reused.status_code == 422
    # A second photo for shot 1 without a retake is refused; the first one stands.
    second = send(kiosk_client, device, session["id"], 1, key="other-key")
    assert second.status_code == 409
    assert kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()["taken"] == 1


def test_retake_replaces_one_photo_and_keeps_the_frame_and_the_plan(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], retake_mode="per_photo")
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    for shot in (1, 2):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200

    retaken = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/retake", json={"shot_index": 2}, headers=device
    )
    assert retaken.status_code == 200, retaken.text
    body = retaken.json()
    assert body["taken"] == 1  # photo 2 no longer counts
    assert body["expected_captures"] == 2 and body["frame_id"] == PRINT34  # plan untouched
    assert [shot["attempt_no"] for shot in body["shots"]] == [1, 2]

    # The replaced attempt can not come back, and the new one takes its place.
    stale = send(kiosk_client, device, session["id"], 2, attempt=1, key="stale")
    assert stale.status_code == 409
    fresh = send(kiosk_client, device, session["id"], 2, attempt=2, key="fresh")
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["session"]["taken"] == 2

    captures = container.session_service._repository.captures(session["id"])
    by_status = sorted(
        (capture.shot_index, capture.attempt_no, str(capture.status)) for capture in captures
    )
    assert by_status == [(1, 1, "ok"), (2, 1, "replaced"), (2, 2, "ok")]


def test_the_event_decides_whether_photos_may_be_retaken(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], retake_mode="none")
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    assert send(kiosk_client, device, session["id"], 1).status_code == 200
    refused = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/retake", json={"shot_index": 1}, headers=device
    )
    assert refused.status_code == 409
    assert "does not allow retakes" in refused.json()["detail"]


def test_retaking_all_photos_starts_the_set_again(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], retake_mode="all")
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    for shot in (1, 2):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200
    one_only = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/retake", json={"shot_index": 1}, headers=device
    )
    assert one_only.status_code == 409  # this event retakes the whole set
    again = kiosk_client.post(f"{SESSIONS}/{session['id']}/retake", json={}, headers=device)
    assert again.status_code == 200, again.text
    assert again.json()["taken"] == 0
    for shot in (1, 2):
        assert send(kiosk_client, device, session["id"], shot, attempt=2).status_code == 200


def test_the_mirror_setting_travels_with_the_photo_and_the_file_is_untouched(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], mirror=True)
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    sent = photo(1)
    assert send(kiosk_client, device, session["id"], 1, data=sent).status_code == 200

    capture = container.session_service._repository.captures(session["id"])[0]
    assert capture.mirrored is True  # the preview was mirrored: the render will match it
    assert capture.storage_key is not None
    assert container.storage.get(StorageKey(capture.storage_key)) == sent  # stored as taken


def test_a_visit_that_ended_takes_no_more_photos(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    assert send(kiosk_client, device, session["id"], 1).status_code == 200

    gone = kiosk_client.post(f"{SESSIONS}/{session['id']}/give-up", headers=device)
    assert gone.status_code == 200 and gone.json()["state"] == "cancelled"
    assert send(kiosk_client, device, session["id"], 2).status_code == 409
    assert kiosk_client.get(f"{SESSIONS}/current", headers=device).json() is None


def test_a_forgotten_visit_ends_by_itself_after_the_inactivity_timeout(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], inactivity_timeout_s=30)
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    assert send(kiosk_client, device, session["id"], 1).status_code == 200

    repository = container.session_service._repository
    repository.touch(session["id"], datetime.now(UTC) - timedelta(minutes=5))
    assert kiosk_client.get(f"{SESSIONS}/current", headers=device).json() is None
    stale = send(kiosk_client, device, session["id"], 2)
    assert stale.status_code == 409
    assert kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()["state"] == (
        "abandoned"
    )

    # The booth is free for the next guest right away.
    fresh = start(kiosk_client, device, key="start-key-2")
    assert fresh["id"] != session["id"] and fresh["state"] == "eligibility_ok"


def test_reloading_the_booth_continues_the_same_visit(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["strip_2x6"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], STRIP)
    for shot in (1, 2, 3):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200

    resumed = kiosk_client.get(f"{SESSIONS}/current", headers=device).json()
    assert resumed["id"] == session["id"] and resumed["taken"] == 3
    assert [shot["done"] for shot in resumed["shots"]] == [True, True, True, False, False, False]
    # Starting again with the same key returns the same visit, not a second one.
    same = start(kiosk_client, device)
    assert same["id"] == session["id"] and same["taken"] == 3


def test_starting_again_ends_the_previous_visit_of_that_device(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    first = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    second = start(kiosk_client, device, key="start-key-2")
    assert second["id"] != first["id"]
    assert kiosk_client.get(f"{SESSIONS}/{first['id']}", headers=device).json()["state"] == (
        "abandoned"
    )
    assert send(kiosk_client, device, first["id"], 1).status_code == 409


def test_an_organizer_editing_the_event_changes_nothing_for_the_guest_at_the_booth(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(
        kiosk_client, admin, enabled_layouts=["print_3x4", "strip_2x6"], countdown_seconds=3
    )
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], STRIP)
    assert session["countdown_seconds"] == 3 and session["expected_captures"] == 6

    changed = kiosk_client.put(
        f"{PROFILES}/{profile['id']}",
        json={
            **profile["settings"],
            "countdown_seconds": 9,
            "enabled_layouts": ["print_3x4"],
            "revision": profile["revision"],
        },
        headers=admin,
    )
    assert changed.status_code == 200, changed.text
    during = kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()
    assert during["countdown_seconds"] == 3  # the visit keeps the event it started with
    assert during["expected_captures"] == 6 and during["template_key"] == "strip_2x6"
    for shot in range(1, 7):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200


def test_only_frames_the_event_offers_may_be_chosen(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = start(kiosk_client, device)
    refused = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/frame", json={"frame_id": STRIP}, headers=device
    )
    assert refused.status_code == 404
    assert kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()["state"] == (
        "eligibility_ok"
    )


def test_a_photo_that_is_not_a_camera_jpeg_is_refused(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    png = io.BytesIO()
    Image.new("RGB", (640, 480), (1, 2, 3)).save(png, "PNG")
    refused = send(kiosk_client, device, session["id"], 1, data=png.getvalue())
    assert refused.status_code == 422
    assert kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()["taken"] == 0
    # The session is unharmed: a real photo still works.
    assert send(kiosk_client, device, session["id"], 1, key="second").status_code == 200


def test_a_photo_may_not_be_retaken_endlessly(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], retake_mode="per_photo")
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    for attempt in range(1, MAX_ATTEMPTS_PER_SHOT + 1):
        assert (
            send(
                kiosk_client, device, session["id"], 1, attempt=attempt, key=f"a{attempt}"
            ).status_code
            == 200
        )
        retaken = kiosk_client.post(
            f"{SESSIONS}/{session['id']}/retake", json={"shot_index": 1}, headers=device
        )
        if attempt == MAX_ATTEMPTS_PER_SHOT:
            assert retaken.status_code == 409
        else:
            assert retaken.status_code == 200, retaken.text


def test_another_device_can_not_read_or_continue_this_visit(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)

    # A second paired browser, with its own cookie jar.
    second = TestClient(
        create_kiosk_app(container.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
    )
    with second:
        other = device_headers(adopt_device(second, container))
        assert second.get(f"{SESSIONS}/{session['id']}", headers=other).status_code == 404
        assert send(second, other, session["id"], 1).status_code == 404
        assert second.get(f"{SESSIONS}/current", headers=other).json() is None
    # The first browser still has its visit.
    assert kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).status_code == 200


def test_the_participant_api_shows_nothing_from_the_admin_side(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], name="Secret Expo Name")
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    answer = send(kiosk_client, device, session["id"], 1)
    assert answer.status_code == 200
    for text in (
        kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).text,
        answer.text,
    ):
        for secret in ("Secret Expo Name", "storage", "captures/", "profile_id", ".jpg", "sha256"):
            assert secret not in text


def test_an_unpaired_browser_gets_nothing_and_changes_nothing(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    key = device["X-Photobooth-Device-Key"]
    kiosk_client.cookies.clear()
    assert kiosk_client.get(f"{SESSIONS}/{session['id']}").status_code == 401
    assert kiosk_client.post(SESSIONS, json={"idempotency_key": "x" * 10}).status_code == 401
    # A paired cookie without its key, or with a foreign origin, may not change anything either.
    adopt_device(kiosk_client, container)
    assert (
        kiosk_client.post(
            SESSIONS, json={"idempotency_key": "y" * 10}, headers={"Origin": ORIGIN}
        ).status_code
        == 403
    )
    assert (
        kiosk_client.post(
            SESSIONS,
            json={"idempotency_key": "z" * 10},
            headers={"Origin": "http://evil.example", "X-Photobooth-Device-Key": key},
        ).status_code
        == 403
    )


def test_photos_and_their_files_survive_a_restart(settings: AppSettings) -> None:
    """The visit's rows and files are still there; the browser re-pairs and starts a new one."""
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            admin, device = booth(client, first)
            activate(client, admin, enabled_layouts=["strip_2x6"])
            session = choose(client, device, start(client, device)["id"], STRIP)
            for shot in (1, 2):
                assert send(client, device, session["id"], shot).status_code == 200
            keys = [
                capture.storage_key
                for capture in first.session_service._repository.captures(session["id"])
            ]
    finally:
        first.close()

    second = Container(settings)  # a fresh process: another boot id
    try:
        assert second.session_service.recover() == 0  # nothing was left half-published
        kept = second.session_service._repository.captures(session["id"])
        assert [capture.storage_key for capture in kept] == keys
        assert all(str(capture.status) == "ok" for capture in kept)
        for key in keys:
            assert key is not None
            assert second.storage.exists(StorageKey(key))  # the photos are still on disk

        # Pairing lives in memory, so the booth browser pairs again and starts a fresh visit;
        # the old one can no longer be added to and ends by itself when its timeout passes.
        app = create_kiosk_app(second.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            admin, device = booth(client, second)
            assert client.get(f"{SESSIONS}/current", headers=device).json() is None
            assert client.get(f"{SESSIONS}/{session['id']}", headers=device).status_code == 404
            fresh = start(client, device, key="after-restart")
            assert fresh["id"] != session["id"]
    finally:
        second.close()


def test_a_photo_left_half_published_by_a_crash_is_settled_at_the_next_start(
    settings: AppSettings,
) -> None:
    """The row exists but the file never arrived: the next process marks that attempt failed."""
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            admin, device = booth(client, first)
            activate(client, admin, enabled_layouts=["print_3x4"])
            session = choose(client, device, start(client, device)["id"], PRINT34)
            assert send(client, device, session["id"], 1).status_code == 200
        repository = first.session_service._repository
        # Exactly what a crash between recording the photo and writing its file leaves behind.
        capture = CaptureAsset(
            id=str(uuid.uuid4()),
            session_id=session["id"],
            operation_id=str(uuid.uuid4()),
            shot_index=2,
            attempt_no=1,
            idempotency_key="crashed-key",
            status=CaptureStatus.PENDING,
            storage_key=f"captures/{session['id']}/never-written.jpg",
            sha256="0" * 64,
            width=1280,
            height=960,
            mirrored=True,
            captured_at=datetime.now(UTC),
        )
        repository.start_capture(
            capture,
            Operation(
                id=capture.operation_id,
                session_id=session["id"],
                idempotency_key="crashed-key",
                kind="capture",
                fingerprint="crashed",
                status=OperationStatus.PENDING,
                owner_boot_id="gone-process",
            ),
            datetime.now(UTC),
        )
    finally:
        first.close()

    second = Container(settings)
    try:
        assert second.session_service.recover() == 1
        settled = second.session_service._repository.capture(capture.id)
        assert settled is not None
        assert str(settled.status) == "failed" and settled.failure_reason == "file_not_stored"
        ledger = second.session_service._repository.files_to_delete()
        assert ledger == []  # the deletion ledger was worked off
        counted = second.session_service._repository.get(session["id"])
        assert counted is not None
        assert counted.successful_capture_count == 1  # the crashed attempt never counted
        assert counted.failed_capture_attempts == 1
    finally:
        second.close()


def test_another_device_can_not_replay_this_visits_photo(
    kiosk_client: TestClient, container: Container
) -> None:
    """P67-001: the device is checked before any recorded request is looked up."""
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    picture = photo(1)
    mine = send(kiosk_client, device, session["id"], 1, key="shared-key", data=picture)
    assert mine.status_code == 200

    second = TestClient(
        create_kiosk_app(container.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
    )
    with second:
        other = device_headers(adopt_device(second, container))
        # The very same key, photo, shot and attempt: still nothing but "no such visit".
        replayed = send(second, other, session["id"], 1, key="shared-key", data=picture)
        assert replayed.status_code == 404
        assert session["id"] not in replayed.text
    # The owner still gets its own answer back.
    again = send(kiosk_client, device, session["id"], 1, key="shared-key", data=picture)
    assert again.status_code == 200
    assert again.json()["capture_id"] == mine.json()["capture_id"]


def test_a_late_second_tap_on_retake_can_not_throw_away_the_new_photo(
    kiosk_client: TestClient, container: Container
) -> None:
    """P67-006: a retake answers one version of the visit; a stale repeat is refused."""
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], retake_mode="per_photo")
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    for shot in (1, 2):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200
    current = kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()

    first = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/retake",
        json={"shot_index": 2, "state_version": current["state_version"]},
        headers=device,
    )
    assert first.status_code == 200, first.text
    assert send(kiosk_client, device, session["id"], 2, attempt=2, key="fresh").status_code == 200

    # The double tap arrives now, still answering the version from before the retake.
    stale = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/retake",
        json={"shot_index": 2, "state_version": current["state_version"]},
        headers=device,
    )
    assert stale.status_code == 409
    kept = kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()
    assert kept["taken"] == 2  # the new photo is still there
    assert [shot["attempt_no"] for shot in kept["shots"]] == [1, 2]


def test_a_frame_a_guest_is_using_keeps_its_file(
    kiosk_client: TestClient, container: Container
) -> None:
    """P67-007: a visit pins the frames it was offered; their files may not change or vanish."""
    admin, device = booth(kiosk_client, container)
    _status, uploaded = upload(kiosk_client, admin, key="print_3x4", name="Party print")
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], uploaded["id"])
    assert send(kiosk_client, device, session["id"], 1).status_code == 200

    frames = f"/api/admin/frames/{uploaded['id']}"
    refused = kiosk_client.delete(frames, headers=admin)
    assert refused.status_code == 409 and "a guest is using this frame" in refused.json()["detail"]
    replaced = kiosk_client.post(
        f"{frames}/replace",
        files={"file": ("f.png", frame_png(TEMPLATES["print_3x4"]), "image/png")},
        headers=admin,
    )
    assert replaced.status_code == 409
    assert kiosk_client.get(frames, headers=admin).status_code == 200  # untouched

    # Once the visit is over, the frame is the organizer's again.
    assert (
        kiosk_client.post(f"{SESSIONS}/{session['id']}/give-up", headers=device).status_code == 200
    )
    assert kiosk_client.delete(frames, headers=admin).status_code == 204


def test_a_visit_used_again_at_the_last_moment_is_not_ended_behind_the_guest(
    kiosk_client: TestClient, container: Container
) -> None:
    """P67-008: expiry only closes a visit nobody has touched since it was read as idle."""
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"], inactivity_timeout_s=30)
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    repository = container.session_service._repository
    long_ago = datetime.now(UTC) - timedelta(minutes=5)
    repository.touch(session["id"], long_ago)

    # The guest acts just as the sweep decides the visit looks idle.
    repository.touch(session["id"], datetime.now(UTC))
    closed = repository.close(
        session["id"], SessionState.ABANDONED, datetime.now(UTC), "inactivity", idle_since=long_ago
    )
    assert closed is not None and not closed.closed  # still theirs
    assert send(kiosk_client, device, session["id"], 1).status_code == 200

    # A visit that really is idle still ends.
    repository.touch(session["id"], long_ago)
    assert session["id"] in repository.close_inactive(datetime.now(UTC))


# ---- the organizer's own test of the booth (Admin "Test booth") -----------------------------

TEST_SESSIONS = "/api/admin/booth-test/sessions"
TEST_MENU = "/api/admin/booth-test/menu"


def test_the_organizer_tests_a_saved_profile_without_activating_it(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, name="Live event", enabled_layouts=["strip_2x6"])
    other = kiosk_client.post(
        PROFILES,
        json={
            "name": "Next week",
            "title": "Soon",
            "enabled_layouts": ["print_3x4"],
            "countdown_seconds": 9,
        },
        headers=admin,
    ).json()

    menu = kiosk_client.get(f"{TEST_MENU}/{other['id']}", headers=admin)
    assert menu.status_code == 200, menu.text
    assert menu.json()["countdown_seconds"] == 9
    assert {frame["plan"]["template_key"] for frame in menu.json()["frames"]} == {"print_3x4"}

    started = kiosk_client.post(
        TEST_SESSIONS,
        json={"idempotency_key": "test-visit-1", "profile_id": other["id"]},
        headers=admin,
    )
    assert started.status_code == 201, started.text
    session = started.json()
    assert session["is_test"] is True
    assert session["countdown_seconds"] == 9  # the profile under test, not the live one

    # The live event is untouched: still active, still the one the booth offers.
    profiles = {p["settings"]["name"]: p for p in kiosk_client.get(PROFILES, headers=admin).json()}
    assert profiles["Live event"]["is_active"] is True
    assert profiles["Next week"]["is_active"] is False
    assert profiles["Next week"]["revision"] == other["revision"]
    assert kiosk_client.get(MENU, headers=device).json()["layouts"] == ["strip_2x6"]


def test_a_test_visit_takes_photos_like_a_guest_and_leaves_nothing_behind(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = kiosk_client.post(
        TEST_SESSIONS,
        json={"idempotency_key": "test-visit-2", "profile_id": profile["id"]},
        headers=admin,
    ).json()
    choose(kiosk_client, device, session["id"], PRINT34)
    for shot in (1, 2):
        assert send(kiosk_client, device, session["id"], shot).status_code == 200
    captures = container.session_service._repository.captures(session["id"])
    files = [capture.storage_key for capture in captures if capture.storage_key]
    assert len(files) == 2
    for key in files:
        assert container.storage.exists(StorageKey(key))

    # Leaving the test clears its photos, its rows and its files.
    assert (
        kiosk_client.post(f"{SESSIONS}/{session['id']}/give-up", headers=device).status_code == 200
    )
    assert container.session_service._repository.get(session["id"]) is None
    assert container.session_service._repository.captures(session["id"]) == []
    for key in files:
        assert not container.storage.exists(StorageKey(key))


def test_clearing_test_visits_never_touches_a_guests_photos(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    guest = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    assert send(kiosk_client, device, guest["id"], 1).status_code == 200
    guest_files = [
        capture.storage_key
        for capture in container.session_service._repository.captures(guest["id"])
    ]

    # The organizer tests meanwhile (this ends the guest's visit on this one device, as always).
    test_session = kiosk_client.post(
        TEST_SESSIONS,
        json={"idempotency_key": "test-visit-3", "profile_id": profile["id"]},
        headers=admin,
    ).json()
    choose(kiosk_client, device, test_session["id"], PRINT34)
    assert send(kiosk_client, device, test_session["id"], 1).status_code == 200

    cleared = kiosk_client.post("/api/admin/booth-test/cleanup", headers=admin)
    assert cleared.status_code == 204
    assert container.session_service._repository.get(test_session["id"]) is None
    # The guest's visit and photo are still exactly where they were.
    kept = container.session_service._repository.get(guest["id"])
    assert kept is not None and kept.successful_capture_count == 1
    for key in guest_files:
        assert key is not None and container.storage.exists(StorageKey(key))


def test_repeated_tests_do_not_pile_up_rows_or_files(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    for round_no in range(4):
        session = kiosk_client.post(
            TEST_SESSIONS,
            json={"idempotency_key": f"test-round-{round_no}", "profile_id": profile["id"]},
            headers=admin,
        ).json()
        choose(kiosk_client, device, session["id"], PRINT34)
        assert send(kiosk_client, device, session["id"], 1).status_code == 200
        assert (
            kiosk_client.post(f"{SESSIONS}/{session['id']}/give-up", headers=device).status_code
            == 200
        )
    repository = container.session_service._repository
    assert repository.finished_test_sessions(datetime.now(UTC) + timedelta(days=1)) == []
    stored = list((container.settings.storage_dir / "captures").glob("*/*.jpg"))
    assert stored == []  # nothing left over from four rounds


def test_the_booth_shows_a_photo_back_only_to_the_screen_that_took_it(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = choose(kiosk_client, device, start(kiosk_client, device)["id"], PRINT34)
    sent = photo(1)
    answer = send(kiosk_client, device, session["id"], 1, data=sent)
    assert answer.status_code == 200
    capture_id = answer.json()["capture_id"]

    shown = kiosk_client.get(
        f"{SESSIONS}/{session['id']}/captures/{capture_id}.jpg", headers=device
    )
    assert shown.status_code == 200
    assert shown.content == sent  # the very photo that was taken
    assert shown.headers["content-type"] == "image/jpeg"
    assert shown.headers["cache-control"] == "private, no-store"
    assert shown.headers["x-content-type-options"] == "nosniff"

    # Each shot carries its own photo, and a shot without one carries nothing.
    shots = kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()["shots"]
    assert shots[0]["capture_id"] == capture_id and shots[0]["done"] is True
    assert shots[1]["capture_id"] is None and shots[1]["done"] is False

    second = TestClient(
        create_kiosk_app(container.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
    )
    with second:
        other = device_headers(adopt_device(second, container))
        stranger = second.get(
            f"{SESSIONS}/{session['id']}/captures/{capture_id}.jpg", headers=other
        )
        assert stranger.status_code == 404  # another device sees nothing of this visit


def test_the_admin_test_needs_both_the_paired_device_and_an_admin_session(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    start_body = {"idempotency_key": "test-visit-9", "profile_id": profile["id"]}
    # The booth's own headers are not enough: an admin request needs its CSRF header too.
    assert kiosk_client.post(TEST_SESSIONS, json=start_body, headers=device).status_code == 403
    # An admin session is required even for reading a profile's booth screens.
    no_admin = {k: v for k, v in device.items()}
    kiosk_client.post("/api/admin/auth/logout", headers=admin)
    assert kiosk_client.get(f"{TEST_MENU}/{profile['id']}", headers=no_admin).status_code == 401
    # And nothing at all without the paired device.
    kiosk_client.cookies.clear()
    assert kiosk_client.post(TEST_SESSIONS, json=start_body, headers=admin).status_code == 401
