"""Event Profile themes and built-in frame selection: persistence, duplication, conflicts."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.frames.builtin import builtin_frame_id
from photobooth.modules.templates.repository import JsonTemplateRepository
from photobooth.modules.themes.domain import PRESETS
from tests.integration.admin_support import login
from tests.unit.test_frame_validator import frame_png

BASE = "/api/admin/profiles"
TEMPLATES = {t.key: t for t in JsonTemplateRepository().latest()}


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Themed",
        "title": "Welcome",
        "available_frames": [
            builtin_frame_id("midnight", key) for key in ("strip_2x6", "print_3x4", "print_4x6")
        ],
    }
    body.update(overrides)
    return body


def _theme(preset: str = "blush_wedding", **changes: str) -> dict[str, Any]:
    tokens = {**PRESETS[preset].tokens, **changes}
    return {"tokens": tokens, "source": "custom" if changes else "preset", "preset": preset}


def test_theme_and_builtin_frames_are_saved_and_normalized(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    theme = _theme(heading="#1a2b3c")
    created = kiosk_client.post(BASE, json=_body(theme=theme), headers=headers)
    assert created.status_code == 201, created.text
    settings = created.json()["settings"]
    assert settings["theme"]["tokens"]["heading"] == "#1A2B3C"  # stored upper case
    assert (
        settings["theme"]["source"] == "custom" and settings["theme"]["preset"] == "blush_wedding"
    )
    assert builtin_frame_id("midnight", "print_4x6") in settings["available_frames"]


def test_extracted_theme_keeps_its_palette(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    theme = {
        "tokens": PRESETS["neon_party"].tokens,
        "source": "extracted",
        "preset": None,
        "palette": ["#112233", "#ddeeff"],
    }
    created = kiosk_client.post(BASE, json=_body(theme=theme), headers=headers).json()
    assert created["settings"]["theme"]["palette"] == ["#112233", "#DDEEFF"]
    too_many = {**theme, "palette": ["#000000"] * 9}
    assert (
        kiosk_client.post(BASE, json=_body(name="x", theme=too_many), headers=headers).status_code
        == 422
    )


def test_switching_between_builtin_and_custom_frames(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    profile = kiosk_client.post(BASE, json=_body(), headers=headers).json()
    custom = kiosk_client.post(
        "/api/admin/frames",
        data={"template_key": "strip_2x6", "name": "Mine"},
        files={"file": ("f.png", frame_png(TEMPLATES["strip_2x6"]), "image/png")},
        headers=headers,
    ).json()
    revision = profile["revision"]
    gold = builtin_frame_id("celebration_gold", "strip_2x6")
    for frames in ([custom["id"]], [gold, custom["id"]], [custom["id"], gold]):
        body = {**_body(available_frames=frames), "revision": revision}
        updated = kiosk_client.put(f"{BASE}/{profile['id']}", json=body, headers=headers)
        assert updated.status_code == 200, updated.text
        assert updated.json()["settings"]["available_frames"] == frames
        revision = updated.json()["revision"]
    # An unknown frame is refused, like before.
    wrong = {**_body(available_frames=["00000000-0000-4000-8000-000000000000"])}
    refused = kiosk_client.put(
        f"{BASE}/{profile['id']}", json={**wrong, "revision": revision}, headers=headers
    )
    assert refused.status_code == 422
    # Built-in frames in use are still read-only, and the custom one is protected while used.
    assert (
        kiosk_client.delete(f"/api/admin/frames/{custom['id']}", headers=headers).status_code == 409
    )


def test_theme_edits_use_revision_conflicts_and_duplicates_copy_the_theme(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    profile = kiosk_client.post(
        BASE, json=_body(theme=_theme("forest_fresh")), headers=headers
    ).json()
    first = kiosk_client.put(
        f"{BASE}/{profile['id']}",
        json={**_body(theme=_theme("sunset_coral")), "revision": profile["revision"]},
        headers=headers,
    )
    assert first.status_code == 200
    stale = kiosk_client.put(
        f"{BASE}/{profile['id']}",
        json={**_body(theme=_theme("neon_party")), "revision": profile["revision"]},
        headers=headers,
    )
    assert stale.status_code == 409
    current = kiosk_client.get(f"{BASE}/{profile['id']}").json()
    assert current["settings"]["theme"]["preset"] == "sunset_coral"

    copy = kiosk_client.post(f"{BASE}/{profile['id']}/duplicate", json={}, headers=headers).json()
    assert copy["settings"]["theme"] == current["settings"]["theme"]
    assert copy["settings"]["available_frames"] == current["settings"]["available_frames"]


def test_theme_and_frames_survive_a_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        with TestClient(
            create_kiosk_app(first.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        ) as client:
            headers = login(client, first)
            created = client.post(
                BASE, json=_body(theme=_theme("celebration_gold")), headers=headers
            ).json()
    finally:
        first.close()

    second = Container(settings)
    second.restore_builtin_files()
    try:
        with TestClient(
            create_kiosk_app(second.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        ) as client:
            login(client, second, create_user=False)
            reloaded = client.get(f"{BASE}/{created['id']}").json()
            assert reloaded["settings"]["theme"] == created["settings"]["theme"]
            assert (
                reloaded["settings"]["available_frames"] == created["settings"]["available_frames"]
            )
            frame_id = builtin_frame_id("midnight", "strip_2x6")
            assert client.get(f"/api/admin/frames/{frame_id}/content").status_code == 200
    finally:
        second.close()
