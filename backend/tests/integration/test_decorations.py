"""Phase 9: the guest decorates the finished photos with a filter and stickers.

Proven here: the booth is offered the filters (with the exact numbers the server applies) and the
sticker files the server pastes; the decorating preview gets the very slots and frame the renderer
uses, and only for the visit's own device; a decoration is checked before anything is made and
stored in one canonical form that is part of the render fingerprint; the finished photos carry it
while the original photos and the frame file stay byte for byte the same.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photobooth.container import Container
from photobooth.modules.decorations.domain import FILTERS
from photobooth.modules.sessions.service import render_fingerprint
from photobooth.modules.storage.domain import StorageKey
from tests.integration.admin_support import adopt_device, device_headers
from tests.integration.test_booth_sessions import PRINT34, SESSIONS, STRIP
from tests.integration.test_outputs_delivery import CANVAS, LAYOUT_OF, reviewing

DECORATIONS = "/api/booth/decorations"


def render_with(
    client: TestClient,
    device: dict[str, str],
    session_id: str,
    decoration: dict[str, Any] | None,
    key: str = "decorated-1",
) -> Any:
    body: dict[str, Any] = {"idempotency_key": key}
    if decoration is not None:
        body["decoration"] = decoration
    return client.post(f"{SESSIONS}/{session_id}/render", json=body, headers=device)


def heart(**overrides: Any) -> dict[str, Any]:
    return {"sticker": "heart", "output": 1, "x": 0.5, "y": 0.5, "size": 0.4, "rotation": 0} | (
        overrides
    )


def finished_image(
    client: TestClient, device: dict[str, str], session_id: str, output: dict[str, Any]
) -> Image.Image:
    answer = client.get(f"{SESSIONS}/{session_id}/outputs/{output['id']}.jpg", headers=device)
    assert answer.status_code == 200
    return Image.open(io.BytesIO(answer.content)).convert("RGB")


# ---- what the booth is offered ---------------------------------------------------------------


def test_the_booth_is_offered_the_filters_and_stickers_the_server_applies(
    kiosk_client: TestClient, container: Container
) -> None:
    device, _session = reviewing(kiosk_client, container, PRINT34)
    answer = kiosk_client.get(DECORATIONS, headers=device)
    assert answer.status_code == 200
    body = answer.json()
    assert [f["key"] for f in body["filters"]] == [preset.key for preset in FILTERS]
    assert body["filters"][2]["matrix"] == list(FILTERS[2].matrix)
    assert len(body["stickers"]) == 12
    assert body["max_stickers_per_photo"] == 12

    sticker = body["stickers"][0]
    image = kiosk_client.get(sticker["url"], headers=device)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    drawn = Image.open(io.BytesIO(image.content))
    assert drawn.mode == "RGBA"
    assert drawn.size == (sticker["width"], sticker["height"])
    assert drawn.getpixel((0, 0))[3] == 0  # transparent around the sticker

    assert kiosk_client.get(f"{DECORATIONS}/stickers/skull.png", headers=device).status_code == 404
    assert kiosk_client.get(f"{DECORATIONS}/stickers/..%2Fx.png", headers=device).status_code in {
        404,
        422,
    }


def test_decorations_need_a_paired_booth(kiosk_client: TestClient) -> None:
    assert kiosk_client.get(DECORATIONS).status_code in {401, 403}
    assert kiosk_client.get(f"{DECORATIONS}/stickers/heart.png").status_code in {401, 403}


# ---- the decorating preview ------------------------------------------------------------------


@pytest.mark.parametrize("frame_id", [PRINT34, STRIP])
def test_the_preview_gets_the_renderers_own_slots_and_the_visits_frame(
    kiosk_client: TestClient, container: Container, frame_id: str
) -> None:
    device, session = reviewing(kiosk_client, container, frame_id)
    answer = kiosk_client.get(f"{SESSIONS}/{session['id']}/decorate", headers=device)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    layout = LAYOUT_OF[frame_id]
    template = container.template_service.get(layout)
    assert body["mirror"] is session["mirror"]
    by_shot = {shot["shot_index"]: shot for shot in session["shots"]}
    assert len(body["outputs"]) == template.outputs_per_session
    for output, group in zip(body["outputs"], template.output_capture_groups, strict=True):
        assert (output["width"], output["height"]) == CANVAS[layout]
        assert [slot["shot_index"] for slot in output["slots"]] == list(group)
        for slot, defined in zip(output["slots"], template.slots, strict=True):
            assert (slot["x"], slot["y"], slot["width"], slot["height"]) == (
                defined.rect.x,
                defined.rect.y,
                defined.rect.w,
                defined.rect.h,
            )
            assert slot["capture_id"] == by_shot[slot["shot_index"]]["capture_id"]
            assert slot["version"] == by_shot[slot["shot_index"]]["version"]

    frame = kiosk_client.get(body["frame_url"], headers=device)
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/png"
    stored = container.session_repository.get(session["id"])
    assert stored is not None and stored.selection is not None
    assert hashlib.sha256(frame.content).hexdigest() == stored.selection.frame_sha256


def test_another_booth_never_sees_a_visits_preview_or_frame(
    kiosk_client: TestClient, container: Container
) -> None:
    _device, session = reviewing(kiosk_client, container, PRINT34)
    other = device_headers(adopt_device(kiosk_client, container))
    for path in ("decorate", "frame.png"):
        answer = kiosk_client.get(f"{SESSIONS}/{session['id']}/{path}", headers=other)
        assert answer.status_code == 404, path


def test_the_preview_is_only_for_a_visit_choosing_its_decorations(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    assert render_with(kiosk_client, device, session["id"], None).status_code == 200
    answer = kiosk_client.get(f"{SESSIONS}/{session['id']}/decorate", headers=device)
    assert answer.status_code == 409


# ---- rendering with a decoration -------------------------------------------------------------


def test_a_decoration_is_made_into_the_photos_and_the_originals_never_change(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    stored = container.session_repository.get(session["id"])
    assert stored is not None and stored.selection is not None
    captures = container.session_repository.captures(session["id"])
    before = {
        c.storage_key: hashlib.sha256(container.storage.get(StorageKey(c.storage_key))).hexdigest()
        for c in captures
        if c.storage_key
    }
    frame_before = hashlib.sha256(
        container.session_service.frame_file(_device_id(kiosk_client, container), session["id"])
    ).hexdigest()

    decoration = {"filter": "mono", "stickers": [heart(x=0.5, y=0.25, size=0.3)]}
    answer = render_with(kiosk_client, device, session["id"], decoration)
    assert answer.status_code == 200, answer.text
    output = answer.json()["outputs"][0]
    image = finished_image(kiosk_client, device, session["id"], output)

    # Black and white photos (the sample photos are coloured), a red heart on top.
    slot = container.template_service.get("print_3x4").slots[0].rect
    r, g, b = image.getpixel((slot.x + slot.w // 3, slot.y + slot.h - 20))
    assert max(r, g, b) - min(r, g, b) <= 3
    hr, hg, hb = image.getpixel((round(0.5 * 900), round(0.25 * 1200)))
    assert hr > 180 and hg < 110 and hb < 130

    # The stored decoration is the canonical text, and nothing original changed.
    row = container.session_service.finished_outputs(session["id"])[0]
    assert row.decoration is not None
    assert json.loads(row.decoration) == {
        "version": 1,
        "filter": "mono",
        "stickers": [heart(x=0.5, y=0.25, size=0.3, rotation=0.0)],
    }
    after = {
        key: hashlib.sha256(container.storage.get(StorageKey(key))).hexdigest() for key in before
    }
    assert after == before
    assert stored.selection.frame_sha256 == frame_before


def test_no_decoration_and_an_empty_one_make_the_same_photos(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    answer = render_with(
        kiosk_client, device, session["id"], {"filter": "none", "stickers": []}, key="empty-key-1"
    )
    assert answer.status_code == 200, answer.text
    row = container.session_service.finished_outputs(session["id"])[0]
    assert row.decoration is None  # an undecorated visit is made exactly as before


@pytest.mark.parametrize(
    "decoration",
    [
        {"filter": "vintage"},
        {"stickers": [heart(sticker="skull")]},
        {"stickers": [heart(output=2)]},  # a 3x4 has one photo
        {"stickers": [heart(x=1.5)]},
        {"stickers": [heart(size=0.0)]},
        {"stickers": [heart() for _ in range(13)]},
        {"stickers": [heart(colour="red")]},
        {"filter": "mono", "frame": "other"},
    ],
)
def test_a_decoration_outside_the_rules_is_refused_and_nothing_is_made(
    kiosk_client: TestClient, container: Container, decoration: dict[str, Any]
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    answer = render_with(kiosk_client, device, session["id"], decoration)
    assert answer.status_code == 422, answer.text
    assert container.session_service.finished_outputs(session["id"]) == []
    current = kiosk_client.get(f"{SESSIONS}/{session['id']}", headers=device).json()
    assert current["state"] == "reviewing"  # the guest can fix it and try again


def test_each_strip_of_a_2x6_carries_only_its_own_stickers(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, STRIP)
    decoration = {"filter": "none", "stickers": [heart(output=2, x=0.5, y=0.92, size=0.5)]}
    answer = render_with(kiosk_client, device, session["id"], decoration)
    assert answer.status_code == 200, answer.text
    first, second = (
        finished_image(kiosk_client, device, session["id"], output)
        for output in answer.json()["outputs"]
    )
    at = (300, round(0.92 * 1800))
    assert first.getpixel(at) != second.getpixel(at)
    r, g, b = second.getpixel(at)
    assert r > 180 and g < 110 and b < 130  # the heart, on strip 2 only


def test_the_same_key_with_another_decoration_is_refused(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    first = render_with(kiosk_client, device, session["id"], {"filter": "sepia"}, key="one-key-1")
    assert first.status_code == 200, first.text
    again = render_with(kiosk_client, device, session["id"], {"filter": "sepia"}, key="one-key-1")
    assert again.status_code == 200
    assert again.json()["outputs"] == first.json()["outputs"]
    other = render_with(kiosk_client, device, session["id"], {"filter": "cool"}, key="one-key-1")
    assert other.status_code == 422
    # A second key (a reload) finds the photos already made, whatever it carries.
    reload = render_with(kiosk_client, device, session["id"], {"filter": "cool"}, key="two-key-2")
    assert reload.status_code == 200
    assert reload.json()["outputs"] == first.json()["outputs"]


def test_the_decoration_is_part_of_the_render_fingerprint(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    visit = container.session_repository.get(session["id"])
    assert visit is not None and visit.selection is not None
    captures = sorted(
        (c for c in container.session_repository.captures(session["id"]) if c.status.value == "ok"),
        key=lambda c: c.shot_index,
    )
    prepare = container.decoration_service.prepare
    choices = [None, {"filter": "warm"}, {"filter": "warm", "stickers": [heart()]}]
    prints = {
        render_fingerprint(visit.selection, captures, visit.mirror, prepare(choice, 1))
        for choice in choices
    }
    assert len(prints) == 3

    answer = render_with(kiosk_client, device, session["id"], choices[2])
    assert answer.status_code == 200, answer.text
    made = container.session_service.finished_outputs(session["id"])[0]
    assert made.render_fingerprint == render_fingerprint(
        visit.selection, captures, visit.mirror, prepare(choices[2], 1)
    )


# ---- inspection fixes ------------------------------------------------------------------------


def test_photos_already_made_are_never_offered_for_decorating_again(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P9-R2: the files of decoration A exist but the finishing step failed. A reload must find
    the visit delivered with A, never a fresh decorating screen that would let B be confirmed."""
    device, session = reviewing(kiosk_client, container, PRINT34)
    who = _device_id(kiosk_client, container)
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
        container.session_service.render(
            who, session["id"], "render-a-key", {"filter": "sepia", "stickers": [heart()]}
        )
    # The page reloads: the booth asks what this device was doing.
    current = kiosk_client.get(f"{SESSIONS}/current", headers=device).json()
    assert current["state"] == "delivered"
    assert len(current["outputs"]) == 1
    assert (
        kiosk_client.get(f"{SESSIONS}/{session['id']}/decorate", headers=device).status_code == 409
    )
    rows = container.session_service.finished_outputs(session["id"])
    assert rows[0].decoration is not None and json.loads(rows[0].decoration)["filter"] == "sepia"


def test_the_decorating_preview_settles_a_half_finished_render_too(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    device, session = reviewing(kiosk_client, container, PRINT34)
    who = _device_id(kiosk_client, container)
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
        container.session_service.render(who, session["id"], "render-a-key", {"filter": "mono"})
    answer = kiosk_client.get(f"{SESSIONS}/{session['id']}/decorate", headers=device)
    assert answer.status_code == 409
    assert container.session_service.read(who, session["id"]).state.value == "delivered"


def test_reading_a_visit_never_ends_it_while_it_is_rendering(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P9-R3: a keep-alive read of a visit that looks idle waits for the render's lock."""
    _device, session = reviewing(kiosk_client, container, PRINT34)
    who = _device_id(kiosk_client, container)
    service = container.session_service
    entered, release = threading.Event(), threading.Event()
    real = service._renderer

    class Paused:
        def render(self, request: Any) -> Any:
            entered.set()
            release.wait(timeout=30)
            return real.render(request)

        def layout(self, *args: Any) -> Any:
            return real.layout(*args)

    monkeypatch.setattr(service, "_renderer", Paused())
    outcome: list[Any] = []
    rendering = threading.Thread(
        target=lambda: outcome.append(service.render(who, session["id"], "slow-render", None))
    )
    rendering.start()
    assert entered.wait(timeout=30)
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE booth_sessions SET last_activity_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                session["id"],
            ),
        )
    seen: list[Any] = []
    reading = threading.Thread(target=lambda: seen.append(service.read(who, session["id"])))
    reading.start()
    reading.join(timeout=1.0)
    assert reading.is_alive()  # it waits for the visit's lock instead of ending it
    release.set()
    rendering.join(timeout=60)
    reading.join(timeout=60)
    assert outcome and outcome[0].session.state.value == "delivered"
    assert seen and seen[0].state.value == "delivered"


def _device_id(client: TestClient, container: Container) -> str:
    from tests.integration.test_outputs_delivery import device_id

    return device_id(client, container)
