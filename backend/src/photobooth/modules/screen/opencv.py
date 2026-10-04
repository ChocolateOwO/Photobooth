"""Infrastructure: this PC's cameras through OpenCV, and the file that remembers the choice.

A camera is opened when a picture of it is first asked for and kept open by a reader thread
while pictures keep being asked for; after a quiet spell it is closed again, so the camera light
goes out and the PC's own browser can use the camera.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import cv2

from photobooth.modules.screen.domain import CameraUnavailableError, PcCameraInfo

log = logging.getLogger("photobooth.screen")

CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 960
JPEG_QUALITY = 92
PROBE_LIMIT = 6
IDLE_SECONDS = 20.0
FIRST_FRAME_SECONDS = 5.0
STALE_SECONDS = 2.0
LIST_CACHE_SECONDS = 30.0


class _Reader:
    """One open camera, read continuously on its own thread."""

    def __init__(self, index: int) -> None:
        self.index = index
        self._lock = threading.Lock()
        self._latest: Any = None
        self._latest_at = 0.0
        self._last_used = time.monotonic()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self.failed = False
        self._thread = threading.Thread(target=self._run, name=f"pc-camera-{index}", daemon=True)
        self._thread.start()

    def alive(self) -> bool:
        return self._thread.is_alive() and not self.failed

    def stop(self) -> None:
        self._stop.set()

    def touch(self) -> None:
        with self._lock:
            self._last_used = time.monotonic()

    def _run(self) -> None:
        capture = cv2.VideoCapture(self.index)
        try:
            if not capture.isOpened():
                self.failed = True
                return
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
            misses = 0
            while not self._stop.is_set():
                ok, image = capture.read()
                now = time.monotonic()
                if ok and image is not None:
                    misses = 0
                    with self._lock:
                        self._latest = image
                        self._latest_at = now
                    self._ready.set()
                else:
                    misses += 1
                    if misses > 50:
                        self.failed = True
                        return
                    time.sleep(0.05)
                with self._lock:
                    idle = now - self._last_used > IDLE_SECONDS
                if idle:
                    return
        except Exception:  # an unplugged camera must never take the booth down
            log.exception("camera %s stopped", self.index)
            self.failed = True
        finally:
            capture.release()
            self._ready.set()

    def latest(self) -> Any:
        self.touch()
        self._ready.wait(FIRST_FRAME_SECONDS)
        with self._lock:
            if self._latest is None or time.monotonic() - self._latest_at > STALE_SECONDS:
                return None
            return self._latest


class OpenCvCameras:
    def __init__(self) -> None:
        self._readers: dict[int, _Reader] = {}
        self._lock = threading.Lock()
        self._listed: list[PcCameraInfo] = []
        self._listed_at: float | None = None

    def _reader(self, index: int) -> _Reader:
        with self._lock:
            reader = self._readers.get(index)
            if reader is None or not reader.alive():
                reader = _Reader(index)
                self._readers[index] = reader
            return reader

    def available(self) -> list[PcCameraInfo]:
        now = time.monotonic()
        with self._lock:
            if self._listed_at is not None and now - self._listed_at < LIST_CACHE_SECONDS:
                return list(self._listed)
            open_now = {i for i, r in self._readers.items() if r.alive()}
        found: list[PcCameraInfo] = []
        for index in range(PROBE_LIMIT):
            if index not in open_now:
                capture = cv2.VideoCapture(index)
                try:
                    if not capture.isOpened():
                        continue
                finally:
                    capture.release()
            found.append(PcCameraInfo(index=index, label=f"Camera {index + 1}"))
        with self._lock:
            self._listed = found
            self._listed_at = time.monotonic()
        return list(found)

    def frame(self, index: int, max_width: int | None) -> bytes:
        if index < 0 or index >= PROBE_LIMIT:
            raise CameraUnavailableError(f"no camera {index}")
        image = self._reader(index).latest()
        if image is None:
            raise CameraUnavailableError(f"camera {index} gives no picture")
        height, width = image.shape[:2]
        if max_width is not None and width > max_width:
            image = cv2.resize(
                image, (max_width, round(height * max_width / width)), interpolation=cv2.INTER_AREA
            )
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise CameraUnavailableError("the picture could not be encoded")
        return bytes(encoded.tobytes())

    def close(self) -> None:
        with self._lock:
            for reader in self._readers.values():
                reader.stop()
            self._readers.clear()


class JsonCameraChoiceStore:
    """The chosen camera index, in `<instance>\\config\\pc-camera.json`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> int | None:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8")).get("index")
        except (OSError, ValueError, AttributeError):
            return None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def save(self, index: int | None) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"index": index}), encoding="utf-8")
        os.replace(tmp, self._path)
