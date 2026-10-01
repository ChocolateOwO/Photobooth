"""Phase 8: the finished photos and the guest's take-home link.

Proven here: the finished photos are 300-DPI sRGB JPEGs made from the visit's own untouched
photos and its pinned frame; a 2x6 visit makes two strips of photos 1-3 and 4-6; they are made
exactly once however the request is repeated; a process that died half-way is settled at the next
start; and the take-home link hands a guest exactly their own photos until it expires or is
revoked, while its token never reaches the database, a backup or anyone else's visit.
"""

from __future__ import annotations

import hashlib
import io
import logging
import sqlite3
import threading
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import segno
from fastapi.testclient import TestClient
from PIL import Image

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.logging import configure_logging
from photobooth.core.migrations import Migrator
from photobooth.core.sqlite_backup import SqliteBackupService
from photobooth.main import KioskAppOptions, create_delivery_app, create_kiosk_app
from photobooth.modules.sessions.domain import (
    Operation,
    OperationStatus,
    OutputAsset,
    OutputStatus,
    SessionState,
    output_key,
)
from photobooth.modules.sessions.service import render_fingerprint
from photobooth.modules.storage.domain import StorageKey
from tests.integration.admin_support import adopt_device, device_headers, login
from tests.integration.test_booth_sessions import (
    CAPTURES,
    PRINT34,
    PRINT46,
    SESSIONS,
    STRIP,
    activate,
    booth,
    choose,
    photo,
    send,
    start,
)

LAYOUT_OF = {PRINT34: "print_3x4", PRINT46: "print_4x6", STRIP: "strip_2x6"}
CANVAS = {"print_3x4": (900, 1200), "print_4x6": (1200, 1800), "strip_2x6": (600, 1800)}


@pytest.fixture
def guests(container: Container) -> Iterator[TestClient]:
    """A phone on the event Wi-Fi: it only ever reaches the delivery listener."""
    app = create_delivery_app(container.registry)
    with TestClient(app, base_url="http://192.168.1.50:18113") as client:
        yield client


def reviewing(
    client: TestClient,
    container: Container,
    frame_id: str,
    photos: dict[int, bytes] | None = None,
    **profile: Any,
) -> tuple[dict[str, str], dict[str, Any]]:
    """A visit whose photos are all taken and confirmed: it waits for its finished photos."""
    admin, device = booth(client, container)
    activate(client, admin, enabled_layouts=[LAYOUT_OF[frame_id]], **profile)
    session = start(client, device)
    choose(client, device, session["id"], frame_id)
    for shot in range(1, CAPTURES[LAYOUT_OF[frame_id]] + 1):
        answer = send(client, device, session["id"], shot, data=(photos or {}).get(shot))
        assert answer.status_code == 200, answer.text
    finished = client.post(f"{SESSIONS}/{session['id']}/finish", headers=device)
    assert finished.status_code == 200, finished.text
    assert finished.json()["state"] == "reviewing"
    return device, finished.json()


def render(
    client: TestClient, device: dict[str, str], session_id: str, key: str = "render-key-1"
) -> Any:
    return client.post(
        f"{SESSIONS}/{session_id}/render", json={"idempotency_key": key}, headers=device
    )


def delivered(
    client: TestClient, container: Container, frame_id: str = PRINT34, **profile: Any
) -> tuple[dict[str, str], dict[str, Any]]:
    device, session = reviewing(client, container, frame_id, **profile)
    answer = render(client, device, session["id"])
    assert answer.status_code == 200, answer.text
    return device, answer.json()


def link(client: TestClient, device: dict[str, str], session_id: str) -> dict[str, Any]:
    answer = client.post(f"{SESSIONS}/{session_id}/delivery", headers=device)
    assert answer.status_code == 200, answer.text
    body: dict[str, Any] = answer.json()
    return body


def token_of(url: str) -> str:
    return url.rsplit("/d/", 1)[1]


def device_id(client: TestClient, container: Container) -> str:
    cookie = client.cookies.get(container.settings.device_cookie_name) or ""
    return hashlib.sha256(cookie.encode()).hexdigest()[:32]


# ---- the finished photos --------------------------------------------------------------------


@pytest.mark.parametrize("frame_id", [PRINT34, PRINT46, STRIP])
def test_finished_photos_are_300dpi_srgb_jpegs_of_the_right_canvas(
    kiosk_client: TestClient, container: Container, frame_id: str
) -> None:
    layout = LAYOUT_OF[frame_id]
    device, session = reviewing(kiosk_client, container, frame_id)
    answer = render(kiosk_client, device, session["id"])
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["state"] == "delivered"
    expected_outputs = 2 if layout == "strip_2x6" else 1
    assert [o["output_index"] for o in body["outputs"]] == list(range(1, expected_outputs + 1))

    for output in body["outputs"]:
        image_answer = kiosk_client.get(
            f"{SESSIONS}/{session['id']}/outputs/{output['id']}.jpg", headers=device
        )
        assert image_answer.status_code == 200
        assert image_answer.headers["content-type"] == "image/jpeg"
        image = Image.open(io.BytesIO(image_answer.content))
        assert image.format == "JPEG"
        assert image.size == CANVAS[layout] == (output["width"], output["height"])
        assert tuple(round(v) for v in image.info["dpi"]) == (300, 300)
        assert image.info.get("icc_profile")  # sRGB tagged, as the print needs


def test_a_2x6_visit_makes_two_strips_of_photos_1_to_3_and_4_to_6(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, STRIP)
    answer = render(kiosk_client, device, session["id"])
    assert answer.status_code == 200, answer.text
    by_shot = {shot["shot_index"]: shot["capture_id"] for shot in session["shots"]}
    rows = container.session_service.finished_outputs(session["id"])
    assert [row.capture_ids for row in rows] == [
        (by_shot[1], by_shot[2], by_shot[3]),
        (by_shot[4], by_shot[5], by_shot[6]),
    ]
    used = [capture for row in rows for capture in row.capture_ids]
    assert len(used) == len(set(used)) == 6  # no photo is used twice, none is left out


def _halves(left: tuple[int, int, int], right: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (1280, 960), left)
    image.paste(Image.new("RGB", (640, 960), right), (640, 0))
    data = io.BytesIO()
    image.save(data, "JPEG", quality=95)
    return data.getvalue()


@pytest.mark.parametrize("mirror", [True, False])
def test_the_print_follows_the_mirror_setting_and_the_originals_are_never_touched(
    kiosk_client: TestClient, container: Container, mirror: bool
) -> None:
    red, blue = (220, 20, 20), (20, 20, 220)
    photos = {1: _halves(red, blue), 2: _halves(red, blue)}
    device, session = reviewing(kiosk_client, container, PRINT34, photos=photos, mirror=mirror)
    captures = container.session_service._repository.captures(session["id"])
    before = {
        c.id: hashlib.sha256(container.storage.get(StorageKey(c.storage_key or ""))).hexdigest()
        for c in captures
    }

    body = render(kiosk_client, device, session["id"]).json()
    output = body["outputs"][0]
    data = kiosk_client.get(
        f"{SESSIONS}/{session['id']}/outputs/{output['id']}.jpg", headers=device
    ).content
    image = Image.open(io.BytesIO(data)).convert("RGB")
    # 3x4 slot 1 is 810 x 540 at (45, 45): look near its left edge, in the middle.
    r, _g, b = image.getpixel((45 + 60, 45 + 270))
    left_is_blue = b > r
    assert left_is_blue is mirror  # the guest saw themselves mirrored; so does the print

    after = {
        c.id: hashlib.sha256(container.storage.get(StorageKey(c.storage_key or ""))).hexdigest()
        for c in captures
    }
    assert after == before  # the originals stay exactly as the camera took them


# ---- exactly once -----------------------------------------------------------------------------


def test_repeating_the_request_makes_the_photos_only_once(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT46)
    first = render(kiosk_client, device, session["id"], key="render-1")
    again = render(kiosk_client, device, session["id"], key="render-1")  # a lost answer
    other = render(kiosk_client, device, session["id"], key="render-2")  # a double tap
    assert first.status_code == again.status_code == other.status_code == 200
    ids = {o["id"] for answer in (first, again, other) for o in answer.json()["outputs"]}
    assert len(ids) == 1
    rows = container.session_service._repository.outputs(session["id"])
    assert len(rows) == 1 and rows[0].status is OutputStatus.OK
    stored = list((container.settings.storage_dir / "outputs" / session["id"]).iterdir())
    assert len(stored) == 1  # one file, no half-made leftovers


def test_simultaneous_requests_make_one_set_of_photos(
    kiosk_client: TestClient, container: Container
) -> None:
    _device, session = reviewing(kiosk_client, container, STRIP)
    who = device_id(kiosk_client, container)
    results: list[Any] = []

    def tap(key: str) -> None:
        results.append(container.session_service.render(who, session["id"], key))

    threads = [threading.Thread(target=tap, args=(f"tap-{n}",)) for n in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(results) == 3
    assert len({tuple(o.id for o in outcome.outputs) for outcome in results}) == 1
    rows = container.session_service._repository.outputs(session["id"])
    assert [row.status for row in rows] == [OutputStatus.OK, OutputStatus.OK]


def test_a_busy_render_worker_records_nothing_and_the_same_request_works_later(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    release = threading.Event()
    blockers = [container.render_queue.submit(release.wait) for _ in range(4)]
    try:
        busy = render(kiosk_client, device, session["id"], key="render-busy")
        assert busy.status_code == 503
        assert busy.headers["retry-after"]
        assert container.session_service._repository.outputs(session["id"]) == []
        assert container.session_service._repository.operation(session["id"], "render-busy") is None
    finally:
        release.set()
        for blocker in blockers:
            blocker.result(timeout=10)
    later = render(kiosk_client, device, session["id"], key="render-busy")
    assert later.status_code == 200 and later.json()["state"] == "delivered"


def test_photos_are_only_made_for_a_visit_that_finished_its_photos(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    session = start(kiosk_client, device)
    choose(kiosk_client, device, session["id"], PRINT34)
    send(kiosk_client, device, session["id"], 1)
    early = render(kiosk_client, device, session["id"])
    assert early.status_code == 409  # still taking photos
    early_link = kiosk_client.post(f"{SESSIONS}/{session['id']}/delivery", headers=device)
    assert early_link.status_code == 409  # nothing to take home yet


def test_another_booth_browser_can_not_see_or_make_a_visits_photos(
    kiosk_client: TestClient, container: Container
) -> None:
    _device, body = delivered(kiosk_client, container)
    output_id = body["outputs"][0]["id"]
    stranger = device_headers(adopt_device(kiosk_client, container))
    peek = kiosk_client.get(f"{SESSIONS}/{body['id']}/outputs/{output_id}.jpg", headers=stranger)
    assert peek.status_code == 404
    assert render(kiosk_client, stranger, body["id"], key="their-render").status_code == 404
    assert (
        kiosk_client.post(f"{SESSIONS}/{body['id']}/delivery", headers=stranger).status_code == 404
    )


# ---- a process that died half-way -------------------------------------------------------------


def _half_published(
    container: Container, session_id: str, *, write_files: bool
) -> tuple[str, list[str]]:
    """A render whose publisher died after T1 (and maybe after writing the files)."""
    service = container.session_service
    session = service._repository.get(session_id)
    assert session is not None and session.selection is not None
    captures = service._counted_captures(session)
    fingerprint = render_fingerprint(session.selection, captures, session.mirror, None)
    data = b"\xff\xd8finished-photo-bytes\xff\xd9"
    operation = Operation(
        id=str(uuid.uuid4()),
        session_id=session_id,
        idempotency_key="crashed-render",
        kind="render",
        fingerprint="crashed",
        status=OperationStatus.PENDING,
        owner_boot_id="gone-process",
    )
    output_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    output = OutputAsset(
        id=output_id,
        session_id=session_id,
        operation_id=operation.id,
        output_index=1,
        status=OutputStatus.PENDING,
        render_fingerprint=fingerprint,
        template_key=session.selection.template_key,
        template_version=session.selection.template_version,
        frame_id=session.selection.frame_id,
        frame_sha256=session.selection.frame_sha256,
        capture_ids=tuple(c.id for c in captures),
        storage_key=output_key(session_id, output_id),
        sha256=hashlib.sha256(data).hexdigest(),
        width=900,
        height=1200,
        byte_size=len(data),
        rendered_at=now,
    )
    service._repository.start_render(operation, [output], now)
    if write_files:
        container.storage.put(StorageKey(output.storage_key or ""), data)
    return operation.id, [output_id]


@pytest.mark.parametrize("write_files", [True, False])
def test_the_next_start_settles_a_render_that_died_half_way(
    settings: AppSettings, write_files: bool
) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        client = TestClient(
            create_kiosk_app(first.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        )
        with client:
            _device, session = reviewing(client, first, PRINT34)
        operation_id, (output_id,) = _half_published(first, session["id"], write_files=write_files)
    finally:
        first.close()

    second = Container(settings)  # a fresh process: another boot id
    try:
        assert second.session_service.recover() == 1
        repository = second.session_service._repository
        settled = repository.output(output_id)
        visit = repository.get(session["id"])
        assert settled is not None and visit is not None
        if write_files:
            assert settled.status is OutputStatus.OK
            assert visit.state is SessionState.DELIVERED
        else:
            assert settled.status is OutputStatus.FAILED
            assert visit.state is SessionState.REVIEWING  # the guest can still get their photos
        operation = repository.operation(session["id"], "crashed-render")
        assert operation is not None and operation.status is not OperationStatus.PENDING
        assert second.session_service.recover() == 0  # settled once, for good
        del operation_id
    finally:
        second.close()


# ---- the take-home link -----------------------------------------------------------------------


def test_the_link_opens_the_guests_own_photos_on_the_delivery_listener(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, body = delivered(kiosk_client, container, STRIP)
    issued = link(kiosk_client, device, body["id"])
    token = token_of(issued["url"])
    assert issued["url"] == f"http://127.0.0.1:18113/d/{token}"
    # The QR code is exactly that link.
    assert issued["qr_svg"] == segno.make(issued["url"], error="m", micro=False).svg_inline(
        scale=1,
        border=4,
        dark="#000000",
        light="#ffffff",
        omitsize=True,
        svgclass="qr",
        title="QR code",
    )
    assert datetime.fromisoformat(issued["expires_at"]) > datetime.now(UTC) + timedelta(days=6)

    page = guests.get(f"/d/{token}")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert "<script" not in page.text
    for output in body["outputs"]:
        assert f"/d/{token}/files/{output['id']}" in page.text
    assert f"/d/{token}/all.zip" in page.text

    first = body["outputs"][0]
    shown = guests.get(f"/d/{token}/files/{first['id']}")
    stored = kiosk_client.get(f"{SESSIONS}/{body['id']}/outputs/{first['id']}.jpg", headers=device)
    assert shown.status_code == 200 and shown.content == stored.content
    assert shown.headers["content-disposition"].startswith("inline")

    saved = guests.get(f"/d/{token}/files/{first['id']}?download=1")
    assert saved.headers["content-disposition"] == 'attachment; filename="photobooth-1.jpg"'

    archive = guests.get(f"/d/{token}/all.zip")
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.content)) as opened:
        assert opened.namelist() == ["photobooth-1.jpg", "photobooth-2.jpg"]
        assert opened.read("photobooth-1.jpg") == stored.content
        assert opened.testzip() is None

    token_row = container.delivery_service._repository.by_hash(
        hashlib.sha256(token.encode()).hexdigest()
    )
    assert token_row is not None
    assert token_row.opened_at is not None
    assert token_row.download_count == 2  # the single save and the ZIP


def test_a_reload_shows_the_same_link_and_a_restart_replaces_it(
    settings: AppSettings,
) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        client = TestClient(
            create_kiosk_app(first.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        )
        with client:
            device, body = delivered(client, first)
            issued = link(client, device, body["id"])
            again = link(client, device, body["id"])
            assert again["url"] == issued["url"]  # the booth screen reloaded: the same code
            who = device_id(client, first)
    finally:
        first.close()

    second = Container(settings)  # a restart: the plaintext is gone from memory
    try:
        guests = TestClient(
            create_delivery_app(second.registry), base_url="http://192.168.1.50:18113"
        )
        old = token_of(issued["url"])
        with guests:
            # Until the booth shows the link again, the guest's copy keeps working.
            assert guests.get(f"/d/{old}").status_code == 200
            replaced = second.session_service.delivery_link(who, body["id"])
            assert replaced.url != issued["url"]
            assert guests.get(f"/d/{old}").status_code == 404  # the old code is revoked
            assert guests.get(f"/d/{token_of(replaced.url)}").status_code == 200
    finally:
        second.close()


def test_simultaneous_link_requests_make_one_live_link(
    kiosk_client: TestClient, container: Container
) -> None:
    _device, body = delivered(kiosk_client, container)
    who = device_id(kiosk_client, container)
    urls: list[str] = []

    def ask() -> None:
        urls.append(container.session_service.delivery_link(who, body["id"]).url)

    threads = [threading.Thread(target=ask) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(urls) == 4 and len(set(urls)) == 1
    with sqlite3.connect(container.settings.db_path) as conn:
        live = conn.execute(
            "SELECT COUNT(*) FROM delivery_tokens WHERE session_id = ? AND revoked_at IS NULL",
            (body["id"],),
        ).fetchone()[0]
    assert live == 1


def test_a_link_hands_out_only_its_own_visits_photos(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, mine = delivered(kiosk_client, container)
    my_token = token_of(link(kiosk_client, device, mine["id"])["url"])

    other_device = device_headers(adopt_device(kiosk_client, container))
    other = start(kiosk_client, other_device, key="other-visit")
    choose(kiosk_client, other_device, other["id"], PRINT34)
    for shot in (1, 2):
        send(kiosk_client, other_device, other["id"], shot)
    kiosk_client.post(f"{SESSIONS}/{other['id']}/finish", headers=other_device)
    theirs = render(kiosk_client, other_device, other["id"], key="other-render").json()
    their_output = theirs["outputs"][0]["id"]

    refused = guests.get(f"/d/{my_token}/files/{their_output}")
    assert refused.status_code == 404
    assert refused.text == "not found"


@pytest.mark.parametrize(
    "path",
    [
        "/d/" + "A" * 43,  # well formed, but nobody's
        "/d/short",
        "/d/" + "x" * 200,
        "/d/" + "A" * 43 + "/files/00000000-0000-4000-8000-000000000000",
        "/d/" + "A" * 43 + "/files/not-an-id",
        "/d/" + "A" * 43 + "/all.zip",
    ],
)
def test_every_wrong_address_gets_the_same_answer(guests: TestClient, path: str) -> None:
    answer = guests.get(path)
    assert answer.status_code == 404
    assert answer.text == "not found"
    assert answer.headers["referrer-policy"] == "no-referrer"


def test_an_expired_or_revoked_link_stops_working(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, body = delivered(kiosk_client, container)
    token = token_of(link(kiosk_client, device, body["id"])["url"])
    assert guests.get(f"/d/{token}").status_code == 200

    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE delivery_tokens SET expires_at = ? WHERE session_id = ?",
            (
                (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                body["id"],
            ),
        )
    expired = guests.get(f"/d/{token}")
    assert expired.status_code == 404 and expired.text == "not found"

    fresh = token_of(link(kiosk_client, device, body["id"])["url"])  # the booth shows it again
    assert fresh != token
    assert guests.get(f"/d/{fresh}").status_code == 200
    assert container.delivery_service.revoke(body["id"]) == 1
    assert guests.get(f"/d/{fresh}").status_code == 404


def test_the_token_never_reaches_the_database_or_a_backup(
    kiosk_client: TestClient, container: Container
) -> None:
    device, body = delivered(kiosk_client, container)
    token = token_of(link(kiosk_client, device, body["id"])["url"])
    record = SqliteBackupService(container.settings.backups_dir).create_backup(
        container.settings.db_path, "dummy"
    )
    container.engine.dispose()  # flush WAL pages so every byte is on disk too
    files = [
        container.settings.db_path,
        container.settings.db_path.with_name(container.settings.db_path.name + "-wal"),
        Path(record.path),
    ]
    needle = token.encode()
    for path in files:
        if path.exists():
            assert needle not in path.read_bytes(), path.name
    with sqlite3.connect(container.settings.db_path) as conn:
        stored = conn.execute("SELECT token_hash FROM delivery_tokens").fetchone()[0]
    assert stored == hashlib.sha256(token.encode()).hexdigest()


def test_one_phone_can_not_keep_the_booth_busy(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, body = delivered(kiosk_client, container, STRIP)
    token = token_of(link(kiosk_client, device, body["id"])["url"])
    answers = [guests.get(f"/d/{token}/all.zip").status_code for _ in range(12)]
    assert answers[:10] == [200] * 10
    assert answers[10:] == [429, 429]


# ---- how a delivered visit ends -----------------------------------------------------------------


def test_the_next_guest_or_a_timeout_completes_a_delivered_visit_and_its_link_still_works(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, body = delivered(kiosk_client, container)
    token = token_of(link(kiosk_client, device, body["id"])["url"])

    start(kiosk_client, device, key="next-guest")  # the next guest presses Start
    ended = container.session_service._repository.get(body["id"])
    assert ended is not None and ended.state is SessionState.COMPLETED
    assert guests.get(f"/d/{token}").status_code == 200  # the first guest's link still works


def test_a_delivered_visit_nobody_touches_completes_on_its_own(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, body = delivered(kiosk_client, container, inactivity_timeout_s=30)
    token = token_of(link(kiosk_client, device, body["id"])["url"])
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE booth_sessions SET last_activity_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                body["id"],
            ),
        )
    assert container.session_service.close_inactive() == [body["id"]]
    ended = container.session_service._repository.get(body["id"])
    assert ended is not None and ended.state is SessionState.COMPLETED
    assert guests.get(f"/d/{token}").status_code == 200


def test_leaving_after_the_photos_were_delivered_completes_the_visit(
    kiosk_client: TestClient, container: Container
) -> None:
    device, body = delivered(kiosk_client, container)
    left = kiosk_client.post(f"{SESSIONS}/{body['id']}/give-up", headers=device)
    assert left.status_code == 200 and left.json()["state"] == "completed"


def test_an_organizers_test_can_be_delivered_and_leaves_nothing_behind(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    key = adopt_device(kiosk_client, container)
    admin = login(kiosk_client, container, key=key)
    device = device_headers(key)
    profile = activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    started = kiosk_client.post(
        "/api/admin/booth-test/sessions",
        json={"idempotency_key": "test-visit-1", "profile_id": profile["id"]},
        headers=admin,
    )
    assert started.status_code == 201, started.text
    visit = started.json()
    choose(kiosk_client, device, visit["id"], PRINT34)
    for shot in (1, 2):
        send(kiosk_client, device, visit["id"], shot, data=photo(shot))
    kiosk_client.post(f"{SESSIONS}/{visit['id']}/finish", headers=device)
    body = render(kiosk_client, device, visit["id"]).json()
    token = token_of(link(kiosk_client, device, visit["id"])["url"])
    assert guests.get(f"/d/{token}").status_code == 200  # the organizer can try it on a phone

    kiosk_client.post(f"{SESSIONS}/{visit['id']}/give-up", headers=device)  # Exit test
    assert guests.get(f"/d/{token}").status_code == 404
    assert not (container.settings.storage_dir / "outputs" / visit["id"]).exists() or not any(
        (container.settings.storage_dir / "outputs" / visit["id"]).iterdir()
    )
    with sqlite3.connect(container.settings.db_path) as conn:
        for table in ("output_assets", "delivery_tokens"):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE session_id = ?",  # noqa: S608
                (visit["id"],),
            ).fetchone()[0]
            assert count == 0, table
    del body


def test_a_failing_delivery_request_never_writes_its_token_to_the_log(
    kiosk_client: TestClient,
    container: Container,
    guests: TestClient,
    thai_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, body = delivered(kiosk_client, container)
    token = token_of(link(kiosk_client, device, body["id"])["url"])
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    logs = thai_root / "logs"
    configure_logging(logs)
    try:

        def explode(_token: str) -> None:
            raise RuntimeError(f"boom while opening /d/{_token}")

        monkeypatch.setattr(container.delivery_service, "open", explode)
        failed = guests.get(f"/d/{token}")
        assert failed.status_code == 404 and failed.text == "not found"
        logging.getLogger("photobooth").info("guest opened http://x:8113/d/%s", token)
        for handler in root.handlers:
            handler.flush()
    finally:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])
    written = "".join(path.read_text(encoding="utf-8") for path in logs.glob("*.log*"))
    assert "delivery request failed: RuntimeError" in written
    assert token not in written


# ---- Codex inspection P8-001 .. P8-008 -------------------------------------------------------

BOOTH_ID = "booth-" + "b" * 30  # the booth browser's own durable id (kept through re-pairing)
BOOTH_HEADER = "X-Photobooth-Booth"


def test_a_restarted_booth_resumes_its_visit_and_replaces_the_link_over_http(
    settings: AppSettings,
) -> None:
    """P8-001: re-pairing renews the cookie, but the booth's own id still owns its visit."""
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        client = TestClient(
            create_kiosk_app(first.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        )
        with client:
            client.headers[BOOTH_HEADER] = BOOTH_ID
            device, body = delivered(client, first)
            old = token_of(link(client, device, body["id"])["url"])
    finally:
        first.close()

    second = Container(settings)  # a restart: new boot, every pairing is gone
    try:
        client = TestClient(
            create_kiosk_app(second.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        )
        guests = TestClient(
            create_delivery_app(second.registry), base_url="http://192.168.1.50:18113"
        )
        with client, guests:
            device = device_headers(adopt_device(client, second))  # the booth pairs again
            assert client.get(f"{SESSIONS}/current").json() is None  # without its id: a stranger
            client.headers[BOOTH_HEADER] = BOOTH_ID
            resumed = client.get(f"{SESSIONS}/current").json()
            assert resumed["id"] == body["id"] and resumed["state"] == "delivered"
            # An <img> sends no header: the pairing remembers which booth it spoke for.
            output = resumed["outputs"][0]["id"]
            client.headers.pop(BOOTH_HEADER)
            image = client.get(f"{SESSIONS}/{body['id']}/outputs/{output}.jpg")
            assert image.status_code == 200
            client.headers[BOOTH_HEADER] = BOOTH_ID
            replaced = token_of(link(client, device, body["id"])["url"])
            assert replaced != old
            assert guests.get(f"/d/{old}").status_code == 404
            assert guests.get(f"/d/{replaced}").status_code == 200
    finally:
        second.close()


def test_a_render_whose_finishing_step_failed_is_settled_not_rendered_again(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P8-002: T1 and the files succeeded, T2 raised; a fresh key must not make a second set."""
    _device, session = reviewing(kiosk_client, container, PRINT34)
    who = device_id(kiosk_client, container)
    repository = container.session_service._repository
    real = repository.finalize_render
    calls = {"n": 0}

    def flaky(operation_id: str, fingerprint: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away for a moment")
        return real(operation_id, fingerprint)

    monkeypatch.setattr(repository, "finalize_render", flaky)
    with pytest.raises(RuntimeError):
        container.session_service.render(who, session["id"], "render-first")
    retried = container.session_service.render(who, session["id"], "render-reloaded-page")
    assert retried.session.state is SessionState.DELIVERED
    rows = repository.outputs(session["id"])
    assert len(rows) == 1 and rows[0].status is OutputStatus.OK  # the first set, settled
    assert repository.pending_operations(session["id"]) == []


def test_an_upkeep_tick_never_ends_a_visit_that_is_rendering(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P8-003: the inactivity sweep waits for the visit's lock and sees the render's activity."""
    _device, session = reviewing(kiosk_client, container, PRINT34)
    who = device_id(kiosk_client, container)
    service = container.session_service
    entered, release = threading.Event(), threading.Event()
    real = service._renderer

    class Paused:
        def render(self, request: Any) -> Any:
            entered.set()
            release.wait(timeout=30)
            return real.render(request)

    monkeypatch.setattr(service, "_renderer", Paused())
    outcome: list[Any] = []
    rendering = threading.Thread(
        target=lambda: outcome.append(service.render(who, session["id"], "slow-render"))
    )
    rendering.start()
    assert entered.wait(timeout=30)
    # While it renders, the visit looks long idle to anyone reading the table.
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE booth_sessions SET last_activity_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                session["id"],
            ),
        )
    swept: list[list[str]] = []
    sweeping = threading.Thread(target=lambda: swept.append(service.close_inactive()))
    sweeping.start()
    sweeping.join(timeout=1.0)
    assert sweeping.is_alive()  # it waits for the visit's lock instead of ending it
    release.set()
    rendering.join(timeout=60)
    sweeping.join(timeout=60)
    assert outcome and outcome[0].session.state is SessionState.DELIVERED
    assert swept == [[]]
    settled = service._repository.get(session["id"])
    assert settled is not None and settled.state is SessionState.DELIVERED


def test_a_test_visit_whose_files_could_not_be_deleted_is_cleaned_up_later(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P8-004: files go before the rows that name them, so a failure leaves nothing orphaned."""
    key = adopt_device(kiosk_client, container)
    admin = login(kiosk_client, container, key=key)
    device = device_headers(key)
    profile = activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    visit = kiosk_client.post(
        "/api/admin/booth-test/sessions",
        json={"idempotency_key": "test-visit-2", "profile_id": profile["id"]},
        headers=admin,
    ).json()
    choose(kiosk_client, device, visit["id"], PRINT34)
    for shot in (1, 2):
        send(kiosk_client, device, visit["id"], shot)
    kiosk_client.post(f"{SESSIONS}/{visit['id']}/finish", headers=device)
    render(kiosk_client, device, visit["id"])
    files = container.session_service._repository.session_files(visit["id"])
    assert len(files) == 3  # two photos and the finished print

    real_delete = container.session_service._files.delete

    def broken(_key: str) -> None:
        raise OSError("file is locked by another program")

    monkeypatch.setattr(container.session_service._files, "delete", broken)
    with pytest.raises(OSError):
        kiosk_client.post(f"{SESSIONS}/{visit['id']}/give-up", headers=device)
    assert container.session_service._repository.get(visit["id"]) is not None  # still known

    monkeypatch.setattr(container.session_service._files, "delete", real_delete)
    assert container.session_service.clear_old_tests(keep_for_seconds=0) == 1
    assert container.session_service._repository.get(visit["id"]) is None
    for stored in files:
        assert not container.storage.exists(StorageKey(stored))


def test_a_remembered_link_is_forgotten_on_time_without_another_request(
    kiosk_client: TestClient, container: Container
) -> None:
    """P8-005: the periodic sweep removes plaintext at its deadline."""
    device, body = delivered(kiosk_client, container)
    link(kiosk_client, device, body["id"])
    delivery = container.delivery_service
    assert len(delivery._plaintext) == 1

    class Later:
        def now(self) -> datetime:
            return datetime.now(UTC) + timedelta(minutes=31)

    delivery._clock = Later()
    container.maintain()
    assert delivery._plaintext == {}


def test_a_missing_original_photo_ends_the_visit_with_a_clear_answer(
    kiosk_client: TestClient, container: Container
) -> None:
    """P8-007: a storage failure reading a photo is a known failure, not a 500."""
    device, session = reviewing(kiosk_client, container, PRINT34)
    capture = container.session_service._repository.captures(session["id"])[0]
    container.storage.delete(StorageKey(capture.storage_key or ""))
    answer = render(kiosk_client, device, session["id"])
    assert answer.status_code == 409
    ended = container.session_service._repository.get(session["id"])
    assert ended is not None and ended.state is SessionState.ERROR
    assert ended.error_code == "photo_missing"
