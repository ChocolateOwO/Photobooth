"""Composition root: the only place that wires concrete infrastructure to services."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Sequence

from photobooth import API_VERSION, __version__
from photobooth.core.admin_gate import AdminAuthenticator, AdminCookieSettings
from photobooth.core.config import AppSettings
from photobooth.core.db import create_sqlite_engine
from photobooth.core.kiosk_pairing import (
    LAUNCHER_TOKEN_FILENAME,
    Clock,
    DeviceCredentialRegistry,
    FilePairingCodeStore,
    LauncherCredential,
    PairingService,
    RuntimeSecretFile,
)
from photobooth.core.uploads import UploadAdmission
from photobooth.core.web import DeviceCookieSettings, ServiceRegistry
from photobooth.modules.assets.domain import AssetNotFoundError
from photobooth.modules.assets.inspector import PillowImageInspector, presentation_copy
from photobooth.modules.assets.repository import SqlAssetRepository
from photobooth.modules.assets.service import AssetService
from photobooth.modules.auth.api import AdminAuthGate
from photobooth.modules.auth.domain import (
    DEV_MIN_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    LoginThrottle,
)
from photobooth.modules.auth.hasher import Argon2PasswordHasher
from photobooth.modules.auth.repository import SqlAdminUserRepository
from photobooth.modules.auth.service import AuthService
from photobooth.modules.auth.sessions import InMemoryAdminSessionStore
from photobooth.modules.booth.domain import (
    EventImage,
    EventOffer,
    LayoutFacts,
    OfferedFrame,
    PreviewBusyError,
    PreviewFailedError,
    StartImageKind,
)
from photobooth.modules.booth.service import BoothService
from photobooth.modules.event_profiles.repository import SqlEventProfileRepository
from photobooth.modules.event_profiles.service import EventProfileService
from photobooth.modules.frames.domain import FrameError
from photobooth.modules.frames.repository import SqlFrameRepository
from photobooth.modules.frames.service import FrameService
from photobooth.modules.frames.validator import PillowFrameValidator
from photobooth.modules.kiosk.service import KioskPairingService
from photobooth.modules.rendering.domain import RenderBusyError, RenderError
from photobooth.modules.rendering.queue import RenderQueue
from photobooth.modules.rendering.renderer import PillowPhotoRenderer, PillowSampleImageFactory
from photobooth.modules.rendering.service import RenderService
from photobooth.modules.storage.local import LocalStorageProvider
from photobooth.modules.system.domain import AppMetaRepository
from photobooth.modules.system.repository import SqlAppMetaRepository
from photobooth.modules.system.service import SystemIdentity, SystemService
from photobooth.modules.templates.domain import TemplateNotFoundError
from photobooth.modules.templates.imaging import PillowTemplateArtist
from photobooth.modules.templates.repository import JsonTemplateRepository
from photobooth.modules.templates.service import TemplateSpecService
from photobooth.modules.themes.domain import ThemeSourceError
from photobooth.modules.themes.extractor import PillowPaletteExtractor
from photobooth.modules.themes.service import ThemeService


class _FrameUsage:
    """Adapter so the frames module can show which profiles offer each photo size."""

    def __init__(self, profiles: SqlEventProfileRepository) -> None:
        self._profiles = profiles

    def names_by_layout(self) -> dict[str, list[str]]:
        return self._profiles.names_by_layout()


class _BackgroundImages:
    """Adapter: the original bytes of an uploaded background, for colour extraction."""

    def __init__(self, assets: AssetService) -> None:
        self._assets = assets

    def background_bytes(self, asset_id: str) -> bytes:
        if not self._assets.exists(asset_id, "background"):
            raise ThemeSourceError("That background image does not exist. Upload it again.")
        try:
            _asset, data = self._assets.content(asset_id)
        except AssetNotFoundError as exc:
            raise ThemeSourceError(
                "That background image does not exist. Upload it again."
            ) from exc
        return data


class _BoothEvent:
    """Adapter: the active Event Profile's participant-facing choices."""

    def __init__(self, profiles: EventProfileService) -> None:
        self._profiles = profiles

    def offer(self) -> EventOffer | None:
        active = self._profiles.get_active()
        if active is None:
            return None
        settings = active.settings
        return EventOffer(
            layouts=settings.enabled_layouts,
            allow_surprise_me=settings.allow_surprise_me,
            theme_tokens=dict(settings.theme.tokens),
            start_button_text=settings.start_button_text,
            logo_asset_id=settings.logo_asset_id,
            background_asset_id=settings.background_asset_id,
            countdown_seconds=settings.countdown_seconds,
        )


class _BoothImages:
    """Adapter: the active event's logo/background through the assets module (StorageProvider).

    Only an asset of the expected kind is used; a missing row or file means "not available".
    Participants get a metadata-free copy (no EXIF/GPS, comments or PNG text), never the
    original upload bytes. The last few copies are kept, keyed by content hash.
    """

    _CACHE_SIZE = 4

    def __init__(self, assets: AssetService) -> None:
        self._assets = assets
        self._copies: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def _clean(self, sha256: str, data: bytes) -> tuple[bytes, str] | None:
        with self._lock:
            cached = self._copies.get(sha256)
        if cached is not None:
            return cached
        try:
            copy = presentation_copy(data)
        except (OSError, ValueError, SyntaxError):
            return None  # unreadable stored file: treated as not available
        with self._lock:
            self._copies[sha256] = copy
            while len(self._copies) > self._CACHE_SIZE:
                self._copies.pop(next(iter(self._copies)))
        return copy

    def version(self, asset_id: str, kind: StartImageKind) -> str | None:
        if not self._assets.exists(asset_id, kind):
            return None
        try:
            return self._assets.get(asset_id).sha256[:16]
        except AssetNotFoundError:
            return None

    def image(self, asset_id: str, kind: StartImageKind) -> EventImage | None:
        if not self._assets.exists(asset_id, kind):
            return None
        try:
            asset, data = self._assets.content(asset_id)
        except AssetNotFoundError:
            return None
        clean = self._clean(asset.sha256, data)
        if clean is None:
            return None
        return EventImage(data=clean[0], media_type=clean[1], version=asset.sha256[:16])


class _BoothFrames:
    """Adapter: name, layout and version of each valid frame of the given photo sizes (nothing
    about files or whether a frame is built-in or uploaded)."""

    def __init__(self, frames: FrameService) -> None:
        self._frames = frames

    def offered(self, layouts: Sequence[str]) -> list[OfferedFrame]:
        return [
            OfferedFrame(
                frame_id=frame.id,
                name=frame.name,
                template_key=frame.template_key,
                template_version=frame.template_version,
                sha256=frame.sha256,
            )
            for frame in self._frames.offered_frames(layouts)
        ]


class _BoothLayouts:
    def __init__(self, templates: TemplateSpecService) -> None:
        self._templates = templates

    def facts(self, template_key: str, version: int) -> LayoutFacts | None:
        try:
            template = self._templates.get(template_key, version)
        except TemplateNotFoundError:
            return None
        return LayoutFacts(
            width_in=template.width_in,
            height_in=template.height_in,
            captures=template.captures_per_session,
            outputs=template.outputs_per_session,
            photos_per_output=template.photos_per_output,
            output_capture_groups=template.output_capture_groups,
        )


class _BoothPreviews:
    """Adapter: the frame's sample output on the shared render queue."""

    def __init__(self, frames: FrameService, renderer: RenderService) -> None:
        self._frames = frames
        self._renderer = renderer

    def sample_output(self, frame_id: str) -> bytes:
        try:
            frame, data = self._frames.content(frame_id)
            future = self._renderer.render_frame_preview(
                frame.template_key, 1, data, frame.template_version
            )
            return future.result().data
        except RenderBusyError as exc:
            raise PreviewBusyError(str(exc)) from exc
        except (RenderError, FrameError, TemplateNotFoundError) as exc:
            raise PreviewFailedError("the sample could not be made") from exc


class Container:
    """Owns process-lifetime resources for one instance."""

    def __init__(self, settings: AppSettings, clock: Clock = time.monotonic) -> None:
        self.settings = settings
        self.boot_id = secrets.token_hex(8)
        self.engine = create_sqlite_engine(settings.db_path)

        self.app_meta: AppMetaRepository = SqlAppMetaRepository(self.engine)
        self.system_service = SystemService(
            self.app_meta,
            SystemIdentity(
                instance=settings.instance,
                app_version=__version__,
                api_version=API_VERSION,
                git_commit=settings.git_commit,
            ),
        )

        self.device_credentials = DeviceCredentialRegistry()
        self.pairing_store = FilePairingCodeStore(settings.runtime_dir)
        self.pairing_store.clear()  # a code from a previous process is never valid
        self.pairing = PairingService(self.pairing_store, self.device_credentials, clock=clock)
        self.kiosk_pairing_service = KioskPairingService(self.pairing)
        self.launcher = LauncherCredential(
            RuntimeSecretFile(settings.runtime_dir, LAUNCHER_TOKEN_FILENAME)
        )

        self.template_service = TemplateSpecService(
            JsonTemplateRepository(), PillowTemplateArtist()
        )
        self.render_queue = RenderQueue(max_pending=4)
        self.render_service = RenderService(
            PillowPhotoRenderer(),
            self.template_service,
            PillowSampleImageFactory(),
            self.render_queue,
        )

        self.storage = LocalStorageProvider(settings.storage_dir)
        self.asset_service = AssetService(
            SqlAssetRepository(self.engine), self.storage, PillowImageInspector()
        )
        self.auth_service = AuthService(
            SqlAdminUserRepository(self.engine),
            Argon2PasswordHasher(),
            InMemoryAdminSessionStore(),
            LoginThrottle(clock),
            monotonic=clock,
            min_password_length=(
                DEV_MIN_PASSWORD_LENGTH
                if settings.instance == "dummy" and settings.profile == "dev"
                else MIN_PASSWORD_LENGTH
            ),
        )
        self.profile_repository = SqlEventProfileRepository(self.engine)
        self.frame_service = FrameService(
            SqlFrameRepository(self.engine),
            self.asset_service,
            PillowFrameValidator(),
            self.template_service,
            usage=_FrameUsage(self.profile_repository),
        )
        self.theme_service = ThemeService(
            _BackgroundImages(self.asset_service), PillowPaletteExtractor()
        )
        self.profile_service = EventProfileService(
            self.profile_repository,
            self.asset_service,
            self.template_service,
            self.frame_service,
        )

        self.registry = ServiceRegistry()
        self.registry.register(SystemService, self.system_service)
        self.registry.register(KioskPairingService, self.kiosk_pairing_service)
        self.registry.register(TemplateSpecService, self.template_service)
        self.registry.register(RenderService, self.render_service)
        self.registry.register(DeviceCredentialRegistry, self.device_credentials)
        self.registry.register(LauncherCredential, self.launcher)
        self.registry.register(AssetService, self.asset_service)
        self.registry.register(UploadAdmission, UploadAdmission(limit=2))
        self.registry.register(AuthService, self.auth_service)
        self.registry.register(EventProfileService, self.profile_service)
        self.registry.register(FrameService, self.frame_service)
        self.registry.register(ThemeService, self.theme_service)
        self.booth_service = BoothService(
            _BoothEvent(self.profile_service),
            _BoothFrames(self.frame_service),
            _BoothLayouts(self.template_service),
            _BoothPreviews(self.frame_service, self.render_service),
            _BoothImages(self.asset_service),
        )
        self.registry.register(BoothService, self.booth_service)
        self.registry.register(AdminAuthenticator, AdminAuthGate(self.auth_service))
        self.registry.register(
            AdminCookieSettings, AdminCookieSettings(f"pb_admin_{settings.instance}")
        )
        self.registry.register(
            DeviceCookieSettings,
            DeviceCookieSettings(settings.device_cookie_name, settings.allowed_origins),
        )

    def restore_builtin_files(self) -> int:
        """Write the packaged built-in frame files into storage when missing (after migrations)."""
        return self.frame_service.ensure_builtin_files()

    def close(self) -> None:
        self.pairing.shutdown()
        self.launcher.clear()
        self.render_queue.shutdown()
        self.engine.dispose()
