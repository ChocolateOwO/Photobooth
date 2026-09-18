"""Built-in frame library: present on fresh setup, valid for its layout, read-only, restorable."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.modules.frames.builtin import (
    FAMILIES,
    LAYOUTS,
    builtin_frame_id,
    builtin_frames,
)
from photobooth.modules.frames.validator import PillowFrameValidator
from photobooth.modules.storage.domain import StorageKey
from photobooth.modules.templates.repository import JsonTemplateRepository
from tests.integration.admin_support import login
from tests.unit.test_frame_validator import frame_png

TEMPLATES = {t.key: t for t in JsonTemplateRepository().latest()}
BASE = "/api/admin/frames"


def _builtin(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [frame for frame in frames if frame["builtin"]]


@pytest.mark.parametrize("frame", builtin_frames(), ids=lambda f: f.filename)
def test_every_packaged_frame_is_valid_for_its_layout(frame: Any) -> None:
    template = TEMPLATES[frame.template_key]
    report = PillowFrameValidator().validate(frame.read(), template)
    assert (report.width, report.height) == (template.width_px, template.height_px)
    assert all(ratio == 1.0 for ratio in report.slot_transparency)
    assert report.warnings == ()


def test_at_least_three_families_cover_every_layout() -> None:
    assert len(FAMILIES) >= 3
    assert {f.name for f in FAMILIES} >= {"Minimal Light", "Midnight", "Celebration Gold"}
    assert {(f.family.id, f.template_key) for f in builtin_frames()} == {
        (family.id, key) for family in FAMILIES for key in LAYOUTS
    }
    assert set(LAYOUTS) == set(TEMPLATES)
    ids = [f.id for f in builtin_frames()]
    assert len(set(ids)) == len(ids)  # fixed, distinct ids
    assert builtin_frame_id("midnight", "strip_2x6") == builtin_frame_id("midnight", "strip_2x6")


def test_fresh_setup_lists_every_builtin_frame_with_its_file_and_sample(
    kiosk_client: TestClient, container: Container
) -> None:
    login(kiosk_client, container)
    listed = _builtin(kiosk_client.get(BASE).json())
    assert len(listed) == len(FAMILIES) * len(LAYOUTS)
    by_id = {frame["id"]: frame for frame in listed}
    for builtin in builtin_frames():
        frame = by_id[builtin.id]
        assert frame["name"] == builtin.family.name and frame["family"] == builtin.family.id
        assert frame["template_key"] == builtin.template_key and frame["status"] == "valid"
        data = builtin.read()
        assert frame["sha256"] == hashlib.sha256(data).hexdigest()
        content = kiosk_client.get(f"{BASE}/{frame['id']}/content")
        assert content.status_code == 200 and content.content == data
    # Built-ins come first in every layout.
    strip = kiosk_client.get(f"{BASE}?template_key=strip_2x6").json()
    assert [f["builtin"] for f in strip] == [True] * len(FAMILIES)
    sample = kiosk_client.get(
        f"{BASE}/{builtin_frame_id('celebration_gold', 'print_4x6')}/preview/1.jpg"
    )
    assert sample.status_code == 200 and sample.content.startswith(b"\xff\xd8")


def test_builtin_frames_can_not_be_replaced_renamed_or_deleted(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    frame_id = builtin_frame_id("midnight", "strip_2x6")
    before = kiosk_client.get(f"{BASE}/{frame_id}/content").content
    replaced = kiosk_client.post(
        f"{BASE}/{frame_id}/replace",
        files={"file": ("f.png", frame_png(TEMPLATES["strip_2x6"]), "image/png")},
        headers=headers,
    )
    assert replaced.status_code == 409 and "Built-in frames" in replaced.json()["detail"]
    renamed = kiosk_client.put(f"{BASE}/{frame_id}/name", json={"name": "Mine"}, headers=headers)
    assert renamed.status_code == 409
    deleted = kiosk_client.delete(f"{BASE}/{frame_id}", headers=headers)
    assert deleted.status_code == 409
    assert kiosk_client.get(f"{BASE}/{frame_id}/content").content == before
    assert kiosk_client.get(f"{BASE}/{frame_id}").json()["name"] == "Midnight"


def test_uploaded_frames_stay_editable_next_to_builtins(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    clash = kiosk_client.post(
        BASE,
        data={"template_key": "strip_2x6", "name": "Midnight"},
        files={"file": ("f.png", frame_png(TEMPLATES["strip_2x6"]), "image/png")},
        headers=headers,
    )
    assert clash.status_code == 422 and "already exists" in clash.json()["detail"]
    mine = kiosk_client.post(
        BASE,
        data={"template_key": "strip_2x6", "name": "My frame"},
        files={"file": ("f.png", frame_png(TEMPLATES["strip_2x6"]), "image/png")},
        headers=headers,
    ).json()
    assert mine["builtin"] is False
    assert kiosk_client.delete(f"{BASE}/{mine['id']}", headers=headers).status_code == 204


def test_missing_builtin_files_are_restored_and_a_bad_package_is_refused(
    container: Container,
) -> None:
    frame = next(iter(builtin_frames()))
    stored = container.frame_service.get(frame.id)
    key = StorageKey(container.asset_service.get(stored.media_asset_id).storage_key)
    container.storage.delete(key)
    assert not container.storage.exists(key)
    assert container.restore_builtin_files() == 1
    assert container.storage.get(key) == frame.read()
    assert container.restore_builtin_files() == 0  # idempotent

    class Damaged:
        id = frame.id

        @staticmethod
        def read() -> bytes:
            return b"tampered"

    container.storage.delete(key)
    with pytest.raises(Exception, match="does not match"):
        container.frame_service.ensure_builtin_files((Damaged(),))  # type: ignore[arg-type]
    assert not container.storage.exists(key)
