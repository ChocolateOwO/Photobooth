"""Composition root: the only place that wires concrete infrastructure to services."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import secrets
import shutil
import socket
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

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
from photobooth.core.sqlite_backup import SqliteBackupService
from photobooth.core.uploads import UploadAdmission
from photobooth.core.web import BoothBindings, DeviceCookieSettings, ServiceRegistry
from photobooth.modules.activity.domain import ActivityType
from photobooth.modules.activity.repository import SqlActivityRepository
from photobooth.modules.activity.service import ActivityService, Visit, VisitFilter
from photobooth.modules.activity.service import LinkFacts as ActivityLinkFacts
from photobooth.modules.assets.domain import AssetNotFoundError, AssetValidationError, UploadLimits
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
    PhotoSlot,
    PreviewBusyError,
    PreviewFailedError,
    StartImageKind,
    layout_label,
)
from photobooth.modules.booth.service import BoothService
from photobooth.modules.decorations.builtin import PackagedStickerLibrary
from photobooth.modules.decorations.domain import DecorationError
from photobooth.modules.decorations.service import DecorationService
from photobooth.modules.delivery.api import DeliveryBudgets
from photobooth.modules.delivery.domain import (
    DeliverableFile,
    DeliveryNotFoundError,
    DeliveryUnavailableError,
)
from photobooth.modules.delivery.qr import SegnoQrEncoder
from photobooth.modules.delivery.repository import SqlDeliveryTokenRepository
from photobooth.modules.delivery.service import DeliveryService, RequestBudget
from photobooth.modules.eligibility.service import AllowAllEligibility
from photobooth.modules.event_profiles.domain import ProfileNotFoundError
from photobooth.modules.event_profiles.repository import SqlEventProfileRepository
from photobooth.modules.event_profiles.service import EventProfileService
from photobooth.modules.frames.domain import FrameError
from photobooth.modules.frames.repository import SqlFrameRepository
from photobooth.modules.frames.service import FrameService
from photobooth.modules.frames.validator import PillowFrameValidator
from photobooth.modules.kiosk.service import KioskPairingService
from photobooth.modules.rendering.domain import (
    CaptureRef,
    Decoration,
    RenderBusyError,
    RenderError,
    StickerPlacement,
    plan_outputs,
)
from photobooth.modules.rendering.queue import RenderQueue
from photobooth.modules.rendering.renderer import PillowPhotoRenderer, PillowSampleImageFactory
from photobooth.modules.rendering.service import RenderService
from photobooth.modules.retention.domain import EventNotFoundError, RetentionError, RetentionPolicy
from photobooth.modules.retention.files import InstanceFolders
from photobooth.modules.retention.repository import SqlRetentionRepository
from photobooth.modules.retention.service import RetentionService
from photobooth.modules.screen.domain import TvAddress
from photobooth.modules.screen.opencv import JsonCameraChoiceStore, OpenCvCameras
from photobooth.modules.screen.service import PcCameraService, TvPairingService
from photobooth.modules.sessions.domain import (
    MAX_CAPTURE_BYTES,
    MAX_CAPTURE_SIDE,
    MIN_CAPTURE_SIDE,
    BoothSession,
    CaptureFacts,
    CaptureRefusedError,
    DecorationRefusedError,
    DeliveryLink,
    EligibilityDecision,
    LayoutOffer,
    OutputLayout,
    OutputStatus,
    RenderedFile,
    RenderFailedError,
    RenderRequest,
    SlotPhoto,
    TransitionRefusedError,
    VisitFacts,
    VisitRetention,
)
from photobooth.modules.sessions.domain import ProfileSnapshot as SessionProfileSnapshot
from photobooth.modules.sessions.domain import RenderBusyError as SessionRenderBusyError
from photobooth.modules.sessions.domain import RetakeMode as SessionRetakeMode
from photobooth.modules.sessions.repository import SqlSessionRepository
from photobooth.modules.sessions.service import BoothSessionService
from photobooth.modules.storage.domain import StorageKey
from photobooth.modules.storage.local import LocalStorageProvider
from photobooth.modules.system.domain import AppMetaRepository, InstanceFacts
from photobooth.modules.system.repository import SqlAppMetaRepository
from photobooth.modules.system.service import SystemDetailsService, SystemIdentity, SystemService
from photobooth.modules.templates.domain import PhotoTemplate, TemplateNotFoundError
from photobooth.modules.templates.imaging import PillowTemplateArtist
from photobooth.modules.templates.repository import JsonTemplateRepository
from photobooth.modules.templates.service import TemplateSpecService
from photobooth.modules.themes.domain import ThemeSourceError
from photobooth.modules.themes.extractor import PillowPaletteExtractor
from photobooth.modules.themes.service import ThemeService

_log = logging.getLogger(__name__)


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

    def offer(self, profile_id: str | None = None) -> EventOffer | None:
        active = (
            self._profiles.get_active() if profile_id is None else self._profiles.get(profile_id)
        )
        if active is None or active.deleted:
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
        # Every slot of a template has the same shape, so the first one describes them all.
        slot = template.slots[0].rect
        return LayoutFacts(
            width_in=template.width_in,
            height_in=template.height_in,
            captures=template.captures_per_session,
            outputs=template.outputs_per_session,
            photos_per_output=template.photos_per_output,
            output_capture_groups=template.output_capture_groups,
            photo_slot=PhotoSlot(width=slot.w, height=slot.h),
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


class _PolicyValues:
    """Adapter: a retention policy's values, in the shape a visit freezes them (P11-9)."""

    def __init__(self, policies: SqlRetentionRepository) -> None:
        self._policies = policies

    def frozen(self, policy_id: str | None) -> VisitRetention:
        policy = self._policies.policy(policy_id) if policy_id else None
        if policy is None:  # never expected: a profile's policy can not be deleted
            policy = next((p for p in self._policies.policies() if p.is_default), RetentionPolicy())
        return VisitRetention(
            policy_id=policy.id,
            policy_name=policy.name,
            originals_days=policy.originals_days,
            outputs_days=policy.outputs_days,
            link_days=policy.link_days,
            records_mode=policy.metadata_mode.value,
            records_days=policy.metadata_days,
        )


class _RetentionChoices:
    """Adapter: the retention policies an Event Profile can select."""

    def __init__(self, policies: SqlRetentionRepository) -> None:
        self._policies = policies

    def exists(self, policy_id: str) -> bool:
        return self._policies.policy(policy_id) is not None

    def default_id(self) -> str:
        return next((p.id for p in self._policies.policies() if p.is_default), "")


class _PolicyUsage:
    """Adapter: which Event Profiles select a retention policy."""

    def __init__(self, profiles: EventProfileService) -> None:
        self._profiles = profiles

    def profiles_using(self, policy_id: str) -> int:
        return self._profiles.profiles_using(policy_id)

    def held(self) -> AbstractContextManager[None]:
        return self._profiles.held()


class _SessionEvent:
    """Adapter: the active Event Profile flattened into the snapshot a session keeps."""

    def __init__(
        self,
        profiles: EventProfileService,
        frames: FrameService,
        templates: TemplateSpecService,
        policies: _PolicyValues,
    ) -> None:
        self._profiles = profiles
        self._frames = frames
        self._templates = templates
        self._policies = policies

    def snapshot(self, profile_id: str | None = None) -> SessionProfileSnapshot | None:
        # No profile named: the event the booth is running. Named: a saved profile the organizer
        # is testing from Admin, which is only read (never activated or changed).
        profile = (
            self._profiles.get_active() if profile_id is None else self._profiles.get(profile_id)
        )
        if profile is None or profile.deleted:
            return None
        settings = profile.settings
        layouts: list[LayoutOffer] = []
        for frame in self._frames.offered_frames(settings.enabled_layouts):
            try:
                template = self._templates.get(frame.template_key, frame.template_version)
            except TemplateNotFoundError:
                continue
            layouts.append(
                LayoutOffer(
                    template_key=frame.template_key,
                    template_version=frame.template_version,
                    layout_label=layout_label(template.width_in, template.height_in),
                    frame_id=frame.id,
                    frame_sha256=frame.sha256,
                    captures=template.captures_per_session,
                    outputs=template.outputs_per_session,
                )
            )
        return SessionProfileSnapshot(
            profile_id=profile.id,
            profile_revision=profile.revision,
            countdown_seconds=settings.countdown_seconds,
            mirror=settings.mirror,
            retake_mode=SessionRetakeMode(str(settings.retake_mode)),
            delivery_mode=str(settings.delivery_mode),
            inactivity_timeout_s=settings.inactivity_timeout_s,
            layouts=tuple(layouts),
            # Frozen now: a later change of the policy never moves this visit's deadlines.
            retention=self._policies.frozen(settings.retention_policy_id),
        )


class _CaptureImages:
    """Adapter: what the server checks about a photo before it is kept."""

    def __init__(self, inspector: PillowImageInspector) -> None:
        self._inspector = inspector
        self._limits = UploadLimits(
            max_bytes=MAX_CAPTURE_BYTES,
            max_width=MAX_CAPTURE_SIDE,
            max_height=MAX_CAPTURE_SIDE,
            min_width=MIN_CAPTURE_SIDE,
            min_height=MIN_CAPTURE_SIDE,
        )

    def inspect(self, data: bytes) -> CaptureFacts:
        try:
            facts = self._inspector.inspect(data, self._limits)
        except AssetValidationError as exc:
            raise CaptureRefusedError(str(exc)) from exc
        if facts.format != "JPEG":
            raise CaptureRefusedError("the booth camera sends JPEG photos")
        return CaptureFacts(
            width=facts.width, height=facts.height, sha256=hashlib.sha256(data).hexdigest()
        )


class _Eligibility:
    """Adapter: the eligibility module answers in the shape the sessions module asks for."""

    def __init__(self, check: AllowAllEligibility) -> None:
        self._check = check

    def check(self, device_id: str, profile_id: str) -> EligibilityDecision:
        decision = self._check.check(device_id, profile_id)
        return EligibilityDecision(
            allowed=decision.allowed, reason=decision.reason, details=decision.details
        )


class _SessionRenderer:
    """Adapter: a visit's finished photos, rendered on the single render worker, with the
    guest's decoration turned into what the renderer applies (matrix numbers, sticker files)."""

    def __init__(
        self,
        renderer: RenderService,
        templates: TemplateSpecService,
        decorations: DecorationService,
    ) -> None:
        self._renderer = renderer
        self._templates = templates
        self._decorations = decorations

    def _template(self, key: str, version: int) -> PhotoTemplate:
        try:
            return self._templates.get(key, version)
        except TemplateNotFoundError as exc:
            raise RenderFailedError("template_missing") from exc

    def layout(
        self, template_key: str, template_version: int, photos: Sequence[tuple[str, int]]
    ) -> list[OutputLayout]:
        template = self._template(template_key, template_version)
        captures = [CaptureRef(capture_id=cid, shot_index=shot) for cid, shot in photos]
        try:
            plans = plan_outputs(template, captures)
        except RenderError as exc:
            raise RenderFailedError("render_failed") from exc
        return [
            OutputLayout(
                output_index=plan.output_index,
                width=template.width_px,
                height=template.height_px,
                slots=tuple(
                    SlotPhoto(
                        capture_id=assignment.capture.capture_id,
                        shot_index=assignment.capture.shot_index,
                        x=assignment.slot.rect.x,
                        y=assignment.slot.rect.y,
                        width=assignment.slot.rect.w,
                        height=assignment.slot.rect.h,
                    )
                    for assignment in plan.assignments
                ),
            )
            for plan in plans
        ]

    def _decorations_for(
        self, template: PhotoTemplate, stored: str | None
    ) -> dict[int, Decoration]:
        decorations: dict[int, Decoration] = {}
        for index in range(1, template.outputs_per_session + 1):
            try:
                chosen = self._decorations.for_output(stored, index)
            except DecorationError as exc:  # a sticker that is no longer offered
                raise RenderFailedError("decoration_missing") from exc
            decorations[index] = Decoration(
                color_matrix=chosen.matrix,
                stickers=tuple(
                    StickerPlacement(
                        png=art.png,
                        x=art.placed.x,
                        y=art.placed.y,
                        size=art.placed.size,
                        rotation=art.placed.rotation,
                    )
                    for art in chosen.stickers
                ),
            )
        return decorations

    def render(self, request: RenderRequest) -> list[RenderedFile]:
        template = self._template(request.template_key, request.template_version)
        photos = {photo.capture_id: photo.data for photo in request.photos}
        captures = [
            CaptureRef(capture_id=photo.capture_id, shot_index=photo.shot_index)
            for photo in request.photos
        ]
        decorations = self._decorations_for(template, request.decoration)
        try:
            future = self._renderer.submit_session(
                template,
                captures,
                _PhotoSource(photos),
                request.frame_png,
                request.mirror,
                decorations,
            )
            rendered = future.result()
        except RenderBusyError as exc:
            raise SessionRenderBusyError() from exc
        except RenderError as exc:
            raise RenderFailedError("render_failed") from exc
        return [
            RenderedFile(
                output_index=output.output_index,
                data=output.data,
                width=output.width,
                height=output.height,
                capture_ids=output.capture_ids,
            )
            for output in rendered
        ]


class _DecorationRules:
    """Adapter: the decorations module checks a guest's decoration for the sessions module."""

    def __init__(self, decorations: DecorationService) -> None:
        self._decorations = decorations

    def prepare(self, raw: object, outputs: int) -> str | None:
        try:
            return self._decorations.prepare(raw, outputs)
        except DecorationError as exc:
            raise DecorationRefusedError(str(exc)) from exc


class _PhotoSource:
    def __init__(self, photos: dict[str, bytes]) -> None:
        self._photos = photos

    def read(self, capture_id: str) -> bytes:
        return self._photos[capture_id]


class _SessionFrames:
    """Adapter: the frame file a visit pinned when its guest confirmed the frame."""

    def __init__(self, frames: FrameService) -> None:
        self._frames = frames

    def frame_png(self, frame_id: str) -> bytes:
        try:
            _frame, data = self._frames.content(frame_id)
        except (FrameError, AssetNotFoundError) as exc:
            raise RenderFailedError("frame_missing") from exc
        return data


class _DeliveredOutputs:
    """Adapter: the finished photos of a visit, for the delivery module (nothing about storage)."""

    def __init__(self, sessions: SqlSessionRepository, storage: LocalStorageProvider) -> None:
        self._sessions = sessions
        self._storage = storage

    def files(self, session_id: str) -> list[DeliverableFile]:
        return [
            DeliverableFile(
                output_id=output.id,
                output_index=output.output_index,
                width=output.width,
                height=output.height,
                byte_size=output.byte_size,
                sha256=output.sha256 or "",
                rendered_at=output.rendered_at,
            )
            for output in self._sessions.outputs(session_id)
            # A finished photo retention took away is no longer on offer.
            if output.status is OutputStatus.OK
            and output.storage_key
            and not output.file_deleted_at
        ]

    def read(self, session_id: str, output_id: str) -> bytes:
        output = self._sessions.output(output_id)
        if (
            output is None
            or output.session_id != session_id
            or output.status is not OutputStatus.OK
            or output.storage_key is None
            or output.file_deleted_at is not None
        ):
            raise DeliveryNotFoundError()
        return self._storage.get(StorageKey(output.storage_key))


class _LinkAddress:
    """Adapter: the address guests' phones reach the delivery listener on.

    An explicit public host wins; a listener bound to one address uses it; a listener on all
    interfaces uses this machine's own LAN address (found without sending anything).
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def base_url(self) -> str:
        host = self._settings.delivery_public_host or self._settings.delivery_host
        if host in {"0.0.0.0", "::", ""}:  # noqa: S104 - reading the bind address, not binding
            host = _lan_ipv4()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self._settings.delivery_port}"


def _tv_url(settings: AppSettings) -> str | None:
    """The address a TV opens to pair, or None when the TV screen listener is off."""
    if settings.screen_port is None:
        return None
    host = settings.screen_host
    if host in {"0.0.0.0", "::", ""}:  # noqa: S104 - reading the bind address, not binding
        host = _lan_ipv4()
    return f"http://{host}:{settings.screen_port}/tv"


def _lan_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: a UDP connect sends no packet
            address = str(probe.getsockname()[0])
        if not address.startswith("127.") and address != "0.0.0.0":  # noqa: S104
            return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        if not address.startswith("127."):
            return address
    except OSError:
        pass
    return "127.0.0.1"


class _SessionLinks:
    """Adapter: the delivery module's link, in the shape the sessions module shows."""

    def __init__(self, delivery: DeliveryService) -> None:
        self._delivery = delivery

    def ensure(self, session_id: str) -> DeliveryLink:
        try:
            issued = self._delivery.ensure(session_id)
        except DeliveryUnavailableError as exc:
            raise TransitionRefusedError("the finished photos are not ready yet") from exc
        return DeliveryLink(
            url=issued.url,
            expires_at=issued.expires_at,
            qr_svg=issued.qr_svg,
            new=issued.new,
            renewed=issued.renewed,
        )

    def revoke(self, session_id: str) -> int:
        return self._delivery.revoke(session_id)


class _LinkLifetime:
    """Adapter: a new take-home link works as long as the visit's frozen policy says."""

    def __init__(self, sessions: SqlSessionRepository) -> None:
        self._sessions = sessions

    def lifetime(self, session_id: str) -> timedelta:
        session = self._sessions.get(session_id)
        days = session.profile.retention.link_days if session else VisitRetention().link_days
        return timedelta(days=days)


class _VisitRetention:
    """Adapter: the sessions module deletes its own visits' files and rows for retention."""

    def __init__(self, sessions: BoothSessionService) -> None:
        self._sessions = sessions

    def purge_originals(self, now: datetime, dry_run: bool) -> tuple[int, int, int]:
        return self._sessions.purge_originals(now, dry_run)

    def purge_outputs(self, now: datetime, dry_run: bool) -> tuple[int, int, int]:
        return self._sessions.purge_outputs(now, dry_run)

    def anonymize_visits(self, now: datetime, dry_run: bool) -> tuple[int, int, int]:
        return self._sessions.anonymize_visits(now, dry_run)

    def delete_visits(self, now: datetime, dry_run: bool) -> tuple[int, int, int]:
        return self._sessions.delete_visits(now, dry_run)

    def delete_event_visits(self, profile_id: str, dry_run: bool) -> tuple[int, int, int]:
        try:
            return self._sessions.delete_event_visits(profile_id, dry_run)
        except TransitionRefusedError as exc:
            raise RetentionError(str(exc)) from exc


class _EventRemoval:
    """Adapter: the event_profiles module removes a deleted profile for good."""

    def __init__(self, profiles: EventProfileService) -> None:
        self._profiles = profiles

    def deleted(self, profile_id: str) -> bool:
        try:
            profile = self._profiles.get(profile_id)
        except ProfileNotFoundError as exc:
            raise EventNotFoundError() from exc
        return profile.deleted_at is not None

    def locked(self, profile_id: str) -> AbstractContextManager[None]:
        return self._profiles.held()

    def remove(self, profile_id: str) -> None:
        if not self._profiles.remove_deleted(profile_id):
            raise RetentionError("only a deleted event can be deleted for good")


class _InstanceFacts:
    """Adapter: the running booth's facts for the System page (no secret, no file name)."""

    def __init__(self, container: Container) -> None:
        self._c = container
        self._started = datetime.now(UTC)

    def facts(self) -> InstanceFacts:
        settings = self._c.settings
        storage = 0
        if settings.storage_dir.is_dir():
            for path in settings.storage_dir.rglob("*"):
                with contextlib.suppress(OSError):
                    if path.is_file():
                        storage += path.stat().st_size
        disk = shutil.disk_usage(settings.data_dir)
        active = self._c.profile_service.get_active()
        last = self._c.retention_service.last_cleanup()
        # Where the booth's screens really are: the kiosk listener when it serves the built screens
        # (Main), else the separate development UI (Dummy's Vite on its UI port) (P12-R7).
        screens = (
            settings.kiosk_port
            if settings.frontend_dist is not None or settings.ui_port is None
            else settings.ui_port
        )
        return InstanceFacts(
            profile=settings.profile,
            started_at=self._started,
            storage_bytes=storage,
            disk_free_bytes=disk.free,
            disk_total_bytes=disk.total,
            kiosk_url=f"http://{settings.kiosk_host}:{screens}",
            delivery_url=_LinkAddress(settings).base_url(),
            active_event=active.settings.name if active else None,
            visits_in_progress=self._c.session_repository.visits_in_progress(),
            last_cleanup_at=last.finished_at if last else None,
            last_cleanup_errors=tuple(last.errors) if last else (),
        )


class _SessionActivity:
    """Adapter: a guest's visit, recorded in the activity log. Organizer tests never are."""

    def __init__(self, activity: ActivityService) -> None:
        self._activity = activity

    def record(self, kind: str, session: BoothSession, /, **facts: str | int | bool) -> None:
        try:
            if session.is_test:
                return
            self._activity.record(
                ActivityType(kind),
                session_id=session.id,
                profile_id=session.event_profile_id,
                payload=facts,
            )
        except Exception as exc:
            _log.warning("activity %s not recorded (%s)", kind, type(exc).__name__)


class _LinkActivity:
    """Adapter: what guests did with their take-home link (never the link itself)."""

    def __init__(self, activity: ActivityService, sessions: SqlSessionRepository) -> None:
        self._activity = activity
        self._sessions = sessions

    def record(self, kind: str, session_id: str, /, **facts: str | int | bool) -> None:
        try:
            session = self._sessions.get(session_id)
            if session is None or session.is_test:
                return
            self._activity.record(
                ActivityType(kind),
                session_id=session_id,
                profile_id=session.event_profile_id,
                payload=facts,
            )
        except Exception as exc:
            _log.warning("activity %s not recorded (%s)", kind, type(exc).__name__)


class _ActivityVisits:
    """Adapter: guests' visits as History and Statistics count them."""

    def __init__(self, sessions: SqlSessionRepository) -> None:
        self._sessions = sessions

    def visits(self, where: VisitFilter) -> list[Visit]:
        return [
            _visit_of(facts)
            for facts in self._sessions.visits(
                since=where.since,
                until=where.until,
                profile_id=where.profile_id,
                states=where.states,
            )
        ]

    def visit(self, session_id: str) -> Visit | None:
        found = self._sessions.visits(session_id=session_id)
        return _visit_of(found[0]) if found else None


def _visit_of(facts: VisitFacts) -> Visit:
    spec = json.loads(facts.decoration) if facts.decoration else {}
    chosen = spec.get("filter")
    return Visit(
        id=facts.id,
        started_at=facts.started_at,
        ended_at=facts.completed_at,
        photos_made_at=facts.photos_made_at,
        state=str(facts.state),
        end_reason=facts.error_code,
        profile_id=facts.profile_id,
        layout=facts.template_key,
        photos=facts.photos,
        failed_attempts=facts.failed_attempts,
        retakes=facts.retakes,
        outputs=facts.outputs,
        filter=chosen if isinstance(chosen, str) and chosen != "none" else None,
        stickers=len(spec.get("stickers", [])),
    )


class _ActivityLinks:
    """Adapter: what became of each visit's links (from the delivery tables; no token)."""

    def __init__(self, tokens: SqlDeliveryTokenRepository) -> None:
        self._tokens = tokens

    def facts(self, session_ids: Sequence[str]) -> Mapping[str, ActivityLinkFacts]:
        return {
            sid: ActivityLinkFacts(issued=f.issued, opened=f.opened, downloads=f.downloads)
            for sid, f in self._tokens.facts(session_ids).items()
        }


class _ProfileNames:
    """Adapter: event names for History (deleted events keep their name)."""

    def __init__(self, profiles: EventProfileService) -> None:
        self._profiles = profiles

    def names(self) -> Mapping[str, str]:
        return {profile.id: profile.settings.name for profile in self._profiles.list_profiles(True)}


class _CaptureFiles:
    """Adapter: photos are written through the StorageProvider, under server-made keys only."""

    def __init__(self, storage: LocalStorageProvider) -> None:
        self._storage = storage

    def put(self, key: str, data: bytes) -> None:
        self._storage.put(StorageKey(key), data)

    def exists(self, key: str) -> bool:
        return self._storage.exists(StorageKey(key))

    def read(self, key: str) -> bytes:
        return self._storage.get(StorageKey(key))

    def delete(self, key: str) -> None:
        self._storage.delete(StorageKey(key))

    def size(self, key: str) -> int:
        return self._storage.size(StorageKey(key))


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
        self.tv_pairing = TvPairingService(self.device_credentials, clock=clock)
        self.pc_cameras = PcCameraService(
            OpenCvCameras(), JsonCameraChoiceStore(settings.config_dir / "pc-camera.json")
        )
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
        self.retention_repository = SqlRetentionRepository(self.engine)
        self.session_repository = SqlSessionRepository(self.engine)
        self.frame_service = FrameService(
            SqlFrameRepository(self.engine),
            self.asset_service,
            PillowFrameValidator(),
            self.template_service,
            usage=_FrameUsage(self.profile_repository),
            # A frame a guest is already using keeps its file until their visit is over.
            visits=self.session_repository,
        )
        self.theme_service = ThemeService(
            _BackgroundImages(self.asset_service), PillowPaletteExtractor()
        )
        self.profile_service = EventProfileService(
            self.profile_repository,
            self.asset_service,
            self.template_service,
            self.frame_service,
            retention=_RetentionChoices(self.retention_repository),
        )

        self.registry = ServiceRegistry()
        self.registry.register(BoothBindings, BoothBindings())
        self.registry.register(SystemService, self.system_service)
        self.registry.register(KioskPairingService, self.kiosk_pairing_service)
        self.registry.register(TvPairingService, self.tv_pairing)
        self.registry.register(PcCameraService, self.pc_cameras)
        self.registry.register(TvAddress, TvAddress(_tv_url(settings)))
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
        self.delivery_tokens = SqlDeliveryTokenRepository(self.engine)
        self.activity_service = ActivityService(
            SqlActivityRepository(self.engine),
            _ActivityVisits(self.session_repository),
            _ActivityLinks(self.delivery_tokens),
            _ProfileNames(self.profile_service),
        )
        self.registry.register(ActivityService, self.activity_service)
        self.delivery_service = DeliveryService(
            self.delivery_tokens,
            _DeliveredOutputs(self.session_repository, self.storage),
            _LinkAddress(settings),
            SegnoQrEncoder(),
            policy=_LinkLifetime(self.session_repository),
            activity=_LinkActivity(self.activity_service, self.session_repository),
        )
        self.registry.register(DeliveryService, self.delivery_service)
        self.decoration_service = DecorationService(PackagedStickerLibrary())
        self.registry.register(DecorationService, self.decoration_service)
        self.registry.register(
            DeliveryBudgets,
            DeliveryBudgets(requests=RequestBudget(limit=120), archives=RequestBudget(limit=10)),
        )
        self.session_service = BoothSessionService(
            self.session_repository,
            _SessionEvent(
                self.profile_service,
                self.frame_service,
                self.template_service,
                _PolicyValues(self.retention_repository),
            ),
            _CaptureImages(PillowImageInspector()),
            _CaptureFiles(self.storage),
            _Eligibility(AllowAllEligibility()),
            boot_id=self.boot_id,
            renderer=_SessionRenderer(
                self.render_service, self.template_service, self.decoration_service
            ),
            frames=_SessionFrames(self.frame_service),
            links=_SessionLinks(self.delivery_service),
            decorations=_DecorationRules(self.decoration_service),
            activity=_SessionActivity(self.activity_service),
        )
        self.registry.register(BoothSessionService, self.session_service)
        self.retention_service = RetentionService(
            self.retention_repository,
            _VisitRetention(self.session_service),
            self.activity_service,
            InstanceFolders(
                settings.instance_root,
                settings.storage_dir,
                settings.backups_dir,
                settings.logs_dir,
                SqliteBackupService(settings.backups_dir).reconcile,
            ),
            _EventRemoval(self.profile_service),
            usage=_PolicyUsage(self.profile_service),
        )
        self.registry.register(RetentionService, self.retention_service)
        self.registry.register(
            SystemDetailsService, SystemDetailsService(self.system_service, _InstanceFacts(self))
        )
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

    def maintain(self) -> None:
        """Periodic upkeep while serving (every step is idempotent and safe to repeat)."""
        self.session_service.maintain()
        self.delivery_service.forget_expired()
        self.retention_service.scheduled()  # at most once an hour

    def close(self) -> None:
        self.pairing.shutdown()
        self.pc_cameras.close()
        self.launcher.clear()
        self.render_queue.shutdown()
        self.engine.dispose()
