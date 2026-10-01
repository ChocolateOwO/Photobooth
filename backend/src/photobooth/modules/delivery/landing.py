"""The guest's landing page: plain HTML, no script, readable on any phone.

Nothing on it comes from anyone but the server (no names, no free text), and the one stylesheet
is pinned by its hash in the Content-Security-Policy, so the page can not be made to run or load
anything else.
"""

from __future__ import annotations

import base64
import hashlib
import html
from collections.abc import Sequence
from datetime import datetime

from photobooth.modules.delivery.domain import DeliverableFile

STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", "Noto Sans Thai", Roboto, sans-serif;
  background: #f4f5f7;
  color: #1c1f24;
  line-height: 1.45;
}
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 40px; }
h1 { margin: 0 0 6px; font-size: 1.7rem; }
.lead { margin: 0 0 18px; color: #4a5160; }
.all {
  display: flex; align-items: center; justify-content: center;
  min-height: 56px; padding: 12px 20px; margin: 0 0 22px;
  border-radius: 999px; background: #1f5fd6; color: #ffffff;
  font-weight: 700; font-size: 1.05rem; text-decoration: none;
}
.photos { list-style: none; margin: 0; padding: 0; display: grid; gap: 18px; }
.photos.pair { grid-template-columns: 1fr 1fr; }
.photo {
  display: flex; flex-direction: column; gap: 10px; padding: 12px;
  border-radius: 16px; background: #ffffff; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
}
.photo img { display: block; width: 100%; height: auto; border-radius: 8px; }
.save {
  display: flex; align-items: center; justify-content: center;
  min-height: 48px; border-radius: 999px; border: 2px solid #1f5fd6;
  color: #1f5fd6; font-weight: 700; text-decoration: none;
}
.note { margin: 22px 0 0; font-size: 0.92rem; color: #4a5160; }
@media (prefers-color-scheme: dark) {
  body { background: #111318; color: #eef0f4; }
  .lead, .note { color: #b9bfcb; }
  .photo { background: #1d2029; box-shadow: none; }
  .all { background: #4f8ff7; color: #0b0d12; }
  .save { border-color: #7fb0ff; color: #a9c8ff; }
}
""".strip()

STYLE_HASH = "sha256-" + base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "img-src 'self'; "
    f"style-src '{STYLE_HASH}'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def download_name(position: int, total: int) -> str:
    return "photobooth.jpg" if total == 1 else f"photobooth-{position}.jpg"


def _until(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.day} {local:%B %Y}, {local:%H:%M}"


def render_page(token: str, files: Sequence[DeliverableFile], expires_at: datetime) -> str:
    base = f"/d/{html.escape(token, quote=True)}"
    total = len(files)
    items = []
    for position, file in enumerate(files, start=1):
        name = download_name(position, total)
        label = "Your photo" if total == 1 else f"Photo {position} of {total}"
        output = html.escape(file.output_id, quote=True)
        items.append(
            '<li class="photo">'
            f'<img src="{base}/files/{output}" alt="{label}" '
            f'width="{file.width}" height="{file.height}">'
            f'<a class="save" href="{base}/files/{output}?download=1" download="{name}">'
            f"Save {'photo' if total == 1 else f'photo {position}'}</a>"
            "</li>"
        )
    layout = "photos pair" if total == 2 else "photos"
    download_all = (
        f'<a class="all" href="{base}/all.zip" download="photobooth-photos.zip">'
        f"Download all {total} photos (ZIP)</a>"
        if total > 1
        else ""
    )
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="robots" content="noindex, nofollow">'
        "<title>Your photos</title>"
        f"<style>{STYLE}</style></head><body><main>"
        "<h1>Your photos</h1>"
        '<p class="lead">Save them to your phone. They are full print quality.</p>'
        f"{download_all}"
        f'<ul class="{layout}">{"".join(items)}</ul>'
        f'<p class="note">This link works until {html.escape(_until(expires_at))}. '
        "Keep it to yourself: anyone with the link can see these photos.</p>"
        "</main></body></html>"
    )
