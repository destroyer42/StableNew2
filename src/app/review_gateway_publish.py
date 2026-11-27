"""Publish Output Library items to the review gateway (RG-120).

The source is the Output Library index (``src/app/site_library_index.py``): its own rebuildable SQLite cache. The one
exception is an image's N5 batch name, read only from the immutable snapshot of the job its embedded job id names
(``job_batch_reader``), and sent only to a gateway that groups its inbox by batch. Each item crosses the boundary as a
manifest naming its library id and SHA-256 plus media bodies
addressed by their own SHA-256; no path, file name or folder ever leaves the PC (RG-100 invariant 3). Publishing is
idempotent by SHA-256 (the manifest goes first and the gateway names the bodies it still lacks, so a body it already
holds is not sent again; an unchanged item is skipped from the ledger) and resumable (the ledger records an item only
once the gateway reports it ready).

Only a job's authoritative outputs are published: video frames and the un-smoothed clip behind a RIFE result stay on
the PC (``src/app/review_gateway_sources.py``; a file whose metadata names it ``retained_source`` included), so they
never reach phone review or Immich. While a job runs, a video with no StableNew metadata yet, or an image that could be
its frame, waits: the job may still be about to record what it is.

Everything here is blocking file and network work for the sync worker thread, never Tk.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from src.app import site_library_video
from src.app.review_gateway_client import GatewayClient, GatewayConflict, GatewayRejected
from src.app.review_gateway_protocol import (
    CONTENT_TYPES,
    RUN_ID,
    ItemRef,
    MediaVariant,
    item_manifest,
    utc_text,
)
from src.app.review_gateway_sources import RETAINED, SourceFilter, may_be_unrecorded_frame
from src.app.review_gateway_store import SyncLedger
from src.app.site_media_files import SiteOutputError, checked_digest, open_scoped
from src.app.site_output_library import LibraryItem, OutputLibrary
from src.app.site_video_playback import VIDEO_LIMIT
from src.pipeline.artifact_contract import OUTPUT_ROLE_RETAINED_SOURCE
from src.state.output_routing import ARCHIVE_DIR_NAME

log = logging.getLogger(__name__)

IMAGE_LIMIT = 64 * 1024 * 1024
PREVIEW_EDGE = 1080
#: A clip at or under this size, already MP4/WebM, is played on the phone from its original (no transcode).
MOBILE_DIRECT_LIMIT = 64 * 1024 * 1024
MOBILE_EDGE = 1280
#: The rolling backfill window; it reaches further back only to where the publisher last caught up.
BACKFILL_DAYS = 3
#: Overlap kept behind the last catch-up, for rows the index adds late.
CAUGHT_UP_MARGIN_DAYS = 1
#: A row whose file was gone is looked at again after this long.
MISSING_RETRY_S = 86400
#: Longest a row that keeps failing is set aside.
MAX_DEFER_S = 600.0
#: Bound on file checks in one look for candidates, so a long run of gone files cannot hold the worker.
MAX_FILE_CHECKS = 2000
MISSING = "missing"
_SKIPPED_FOLDERS = (ARCHIVE_DIR_NAME, ".stablenew-library")
_RUN_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_SEED = re.compile(r"-?[0-9]{1,19}")
_PROMPT_EXCERPT = 240
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})

Transcode = Callable[[BinaryIO, Path, Callable[[], bool]], bool]


@dataclass
class PublishResult:
    published: int = 0
    skipped: int = 0
    pending: int = 0


@dataclass(frozen=True)
class _Body:
    variant: MediaVariant
    data: bytes | None = None
    path: Path | None = None


def run_id_for(rel_path: str, created_at: datetime) -> str:
    """The output run folder when the item lives in one, else a dated group named after its top folder."""

    parts = Path(rel_path).parts[:-1]
    for part in parts:
        if RUN_ID.fullmatch(part):
            return part
    top = _RUN_SAFE.sub("_", parts[0]).strip(" .")[:64] if parts else ""
    return f"{created_at.astimezone(UTC):%Y%m%d}_000000_{top or 'output'}"


def _display(item: LibraryItem) -> dict[str, Any]:
    prompt = " ".join(item.prompt.split())
    display: dict[str, Any] = {
        "model": item.model or "",
        "workflow": item.workflow or "",
        "prompt_excerpt": prompt[:_PROMPT_EXCERPT],
    }
    if item.seed is not None and _SEED.fullmatch(item.seed):
        display["seed"] = int(item.seed)
    return display


def encode_preview_1080(stream: BinaryIO, mime: str) -> tuple[bytes, str, int, int] | None:
    """The phone rendition: a WebP (JPEG when WebP is unavailable) with a long edge of at most 1080 px, never
    enlarged; ``None`` when the image cannot be decoded."""

    try:
        with Image.open(stream) as image:
            if image.width * image.height > site_library_video.MAX_PIXELS:
                return None
            image.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            for format_name, content_type, quality in (
                ("WEBP", "image/webp", 80),
                ("JPEG", "image/jpeg", 82),
            ):
                output = io.BytesIO()
                try:
                    rgb.save(output, format_name, quality=quality)
                except OSError:
                    continue
                return output.getvalue(), content_type, rgb.width, rgb.height
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None
    return None


def ffmpeg_mobile_transcode(source: BinaryIO, target: Path, cancelled: Callable[[], bool]) -> bool:
    """H.264/AAC MP4 at most 1280 px, low priority and bounded; ``False`` when FFmpeg is absent or fails.

    ``source`` is an already verified handle (``open_scoped``). The input is read with the same demuxer and protocol
    allow-list as the Library's poster extraction, so a crafted container cannot make FFmpeg read another file.
    """

    from src.pipeline.video import resolve_ffmpeg_executable
    from src.utils.managed_process import run_bounded

    tool = resolve_ffmpeg_executable()
    if tool is None:
        return False
    scale = (
        f"scale=w='min(iw,{MOBILE_EDGE})':h='min(ih,{MOBILE_EDGE})'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    source.seek(0)
    outcome = run_bounded(
        [
            str(tool),
            *site_library_video.INPUT_OPTIONS,
            "-nostdin",
            "-i",
            "fd:",
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-vf",
            scale,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-y",
            str(target),
        ],
        timeout_seconds=600,
        max_stdout_bytes=64 * 1024,
        max_stderr_bytes=4096,
        stdin_file=source,
        below_normal=True,
        cancel=cancelled,
        memory_limit_mb=1024,
        allow_unenforced_memory_limit=True,
    )
    return outcome.returncode == 0 and target.is_file() and target.stat().st_size > 0


BatchOf = Callable[[Path], Mapping[str, Any] | None]


def job_batch_reader(
    repository: Any,
    identity: Callable[[Any], Mapping[str, Any] | None],
    *,
    job_id_of: Callable[[Path], str] | None = None,
) -> BatchOf:
    """The N5 batch of the job that wrote an image (``provenance.metadata.batch``), for inbox grouping.

    The job is named by the image's own embedded job id and read from the job repository's immutable snapshot (read
    only); ``identity`` is N5's ``batch_identity``, injected so this module stays free of controller imports. A batch
    without a name (a Video Workflow or retry batch shares the key) is no batch here. Only images are looked up: N5
    batches are image batches. Any failure is ``None``: the item is then grouped by its run folder.
    """

    def read(path: Path) -> Mapping[str, Any] | None:
        from src.review.review_evidence import image_source_job

        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            return None
        try:
            job_id = (job_id_of or image_source_job)(path)
            entry = repository.get_job(job_id) if job_id else None
            batch = identity(getattr(entry, "snapshot", None) or {})
        except Exception:  # noqa: BLE001 - grouping is display only; it must never hold publishing back
            log.debug("Review gateway publish could not read an item's batch")
            return None
        if batch is None or not isinstance(batch.get("name"), str):
            return None
        listed = batch.get("cell")
        cell: Mapping[str, Any] = listed if isinstance(listed, Mapping) else {}
        return {
            "batch_id": batch.get("batch_id"),
            "name": batch["name"],
            "cell": {"pack": cell.get("pack_name"), "model": cell.get("model")},
        }

    return read


class GatewayPublisher:
    def __init__(
        self,
        library: OutputLibrary,
        ledger: SyncLedger,
        *,
        transcode: Transcode | None = ffmpeg_mobile_transcode,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch_of: BatchOf | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._library = library
        self._ledger = ledger
        self._transcode = transcode
        self._now = now
        self._batch_of = batch_of
        self._sources = SourceFilter(library.root)
        self._monotonic = monotonic
        #: key -> (index version, failures, not before): rows set aside so they never keep older rows waiting.
        self._deferred: dict[str, tuple[str, int, float]] = {}

    def _batch(self, client: GatewayClient, path: Path) -> Mapping[str, Any] | None:
        """The item's batch, only for a gateway that groups by it (an older one's schema refuses the field)."""

        if self._batch_of is None or "item_batch" not in client.features:
            return None
        try:
            return self._batch_of(path)
        except Exception:  # noqa: BLE001 - grouping is display only; it must never hold publishing back
            log.debug("Review gateway publish could not read an item's batch")
            return None

    @property
    def root(self) -> Path:
        return self._library.root

    def publish_since(self) -> int:
        """The oldest moment ever published, in microseconds; fixed the first time the worker publishes."""

        stored = self._ledger.get_meta("publish_since")
        if stored.isdigit():
            return int(stored)
        since = int((self._now().timestamp() - BACKFILL_DAYS * 86400) * 1_000_000)
        self._ledger.set_meta({"publish_since": str(since)})
        return since

    def _microseconds(self, **ago: float) -> int:
        return int((self._now() - timedelta(**ago)).timestamp() * 1_000_000)

    def window_start(self) -> int:
        """Where a look begins: the rolling window, or earlier while a backlog since the last catch-up remains."""

        floor = self.publish_since()
        stored = self._ledger.get_meta("publish_caught_up_at")
        if not stored.isdigit():
            return floor
        caught_up = int(stored) - CAUGHT_UP_MARGIN_DAYS * 86400 * 1_000_000
        return max(floor, min(self._microseconds(days=BACKFILL_DAYS), caught_up))

    def candidates(
        self, limit: int, *, newer_than: int | None = None
    ) -> list[tuple[str, LibraryItem]]:
        """Up to ``limit`` unpublished (or changed) index rows, newest first.

        Rows set aside after a failure are passed over, and rows whose file is gone are recorded as ``missing``, so
        neither keeps the rows behind them waiting. ``newer_than`` (microseconds) looks only at fresh rows.
        """

        self._library.start()
        since = self.window_start() if newer_than is None else newer_than
        now = self._monotonic()
        found: list[tuple[str, LibraryItem]] = []
        offset = checks = 0
        waiting = False
        while len(found) < limit and checks < MAX_FILE_CHECKS:
            with self._library.store.connection() as db:
                rows = list(
                    db.execute(
                        "SELECT key, version, body FROM media WHERE enriched = 1 AND timestamp >= ?"
                        " ORDER BY timestamp DESC, key LIMIT 256 OFFSET ?",
                        (since, offset),
                    )
                )
            if not rows:
                break
            offset += len(rows)
            known_rows = self._ledger.published_many([str(row["key"]) for row in rows])
            gone: list[tuple[str, str, str, str]] = []
            for row in rows:
                key, version = str(row["key"]), str(row["version"])
                known = known_rows.get(key)
                if known is not None and known["version"] == version and not self._retry(known):
                    continue
                deferred = self._deferred.get(key)
                if deferred is not None and deferred[0] == version and now < deferred[2]:
                    # A row that has only just started failing still counts as work to do.
                    waiting = waiting or deferred[1] < 5
                    continue
                item = LibraryItem.from_row(row)
                checks += 1
                if os.path.lexists(self.root / item.path) or not self.root.is_dir():
                    found.append((key, item))
                elif known is not None and known["state"] == "published":
                    # A published row stays as it is: phone decisions are resolved through it.
                    self.defer(key, version, MAX_DEFER_S)
                else:
                    gone.append((key, version, item.path, item.kind))
                if len(found) >= limit or checks >= MAX_FILE_CHECKS:
                    break
            if gone:
                self._ledger.mark_missing(gone, utc_text(self._now()))
        if newer_than is None and not found and not waiting and checks < MAX_FILE_CHECKS:
            self._note_caught_up(since)
        return found

    def _retry(self, known: Mapping[str, Any]) -> bool:
        if known["state"] != MISSING:
            return False
        age = self._now() - datetime.fromisoformat(str(known["at"]).replace("Z", "+00:00"))
        return age >= timedelta(seconds=MISSING_RETRY_S)

    def _note_caught_up(self, since: int) -> None:
        with self._library.store.connection() as db:
            unread = db.execute(
                "SELECT 1 FROM media WHERE enriched = 0 AND kind = 'image' AND timestamp >= ? LIMIT 1",
                (since,),
            ).fetchone()
        if unread is None:
            self._ledger.set_meta({"publish_caught_up_at": str(self._microseconds())})

    def defer(self, key: str, version: str, seconds: float | None = None) -> None:
        """Pass this row over for a while: ``seconds``, or longer each time it fails again."""

        previous = self._deferred.get(key)
        failures = previous[1] + 1 if previous is not None and previous[0] == version else 1
        if seconds is None:
            seconds = min(MAX_DEFER_S, 2.0 ** min(failures - 1, 10))
        self._deferred[key] = (version, failures, self._monotonic() + seconds)

    def publish(
        self,
        client: GatewayClient,
        *,
        limit: int,
        cancel: Event,
        allow_transcode: Callable[[], bool] = lambda: True,
        hold_unlabelled_video: bool = False,
        newer_than: int | None = None,
    ) -> PublishResult:
        """``hold_unlabelled_video`` (a job is running) leaves a video without StableNew metadata, and an image that
        could be its frame, pending."""

        result = PublishResult()
        rows = (
            self.candidates(limit)
            if newer_than is None
            else self.candidates(limit, newer_than=newer_than)
        )
        for key, item in rows:
            if cancel.is_set():
                break
            version = json.dumps(list(item.version))
            if hold_unlabelled_video and (
                (item.kind == "video" and item.provenance == "unknown")
                or may_be_unrecorded_frame(item)
            ):
                result.pending += 1
                self.defer(key, version, 10.0)
                continue
            try:
                state = self._publish_one(client, key, item, cancel, allow_transcode)
            except (GatewayConflict, GatewayRejected):
                result.pending += 1
                self.defer(key, version)
                continue
            except (SiteOutputError, OSError):
                log.debug("Review gateway publish deferred an item that changed or is unreadable")
                result.pending += 1
                self.defer(key, version)
                continue
            if state == "published":
                result.published += 1
            elif state == "pending":
                result.pending += 1
                if not cancel.is_set():
                    self.defer(key, version)
            else:
                result.skipped += 1
        if newer_than is None and not hold_unlabelled_video and len(rows) < limit:
            self._add_renditions(client, limit - len(rows), cancel, result)
        return result

    def _add_renditions(
        self, client: GatewayClient, limit: int, cancel: Event, result: PublishResult
    ) -> None:
        """Images published before every image had a phone rendition are sent again, a few at a time when idle.

        Only ever adds: a row that is gone, changed or now excluded is marked done and stays as it was.
        """

        for key in self._ledger.without_rendition(limit):
            if cancel.is_set():
                return
            with self._library.store.connection() as db:
                row = db.execute(
                    "SELECT body, version FROM media WHERE key = ? AND enriched = 1", (key,)
                ).fetchone()
            known = self._ledger.published(key)
            item = LibraryItem.from_row(row) if row is not None else None
            if (
                item is None
                or known is None
                or known["version"] != row["version"]
                or not os.path.lexists(self.root / item.path)
                or self._sources.exclusion(item)
            ):
                self._ledger.set_rendition(key)
                continue
            try:
                state = self._publish_one(client, key, item, cancel, lambda: False)
            except (GatewayConflict, GatewayRejected, SiteOutputError, OSError):
                self._ledger.set_rendition(
                    key
                )  # it stays as published; the phone shows the original
                continue
            if state == "published":
                result.published += 1

    def _skip(self, key: str, item: LibraryItem, state: str) -> str:
        known = self._ledger.published(key)
        if known is not None and known["state"] == "published":
            self.defer(key, json.dumps(list(item.version)), MAX_DEFER_S)
            return state  # already on the phone: its row still resolves the owner's decisions
        self._ledger.mark_published(
            key,
            json.dumps(list(item.version)),
            item.path,
            "",
            item.kind,
            state,
            utc_text(self._now()),
        )
        return state

    def _publish_one(
        self,
        client: GatewayClient,
        key: str,
        item: LibraryItem,
        cancel: Event,
        allow_transcode: Callable[[], bool],
    ) -> str:
        folder = Path(item.path).parts[0] if Path(item.path).parts else ""
        if folder in _SKIPPED_FOLDERS or item.kind not in ("image", "video"):
            return self._skip(key, item, "skipped")
        if item.role == OUTPUT_ROLE_RETAINED_SOURCE:
            return self._skip(key, item, RETAINED)
        excluded = self._sources.exclusion(item)
        if excluded:
            return self._skip(key, item, excluded)
        if item.mime not in CONTENT_TYPES:
            return self._skip(key, item, "unsupported")
        size = item.version[2]
        limit = IMAGE_LIMIT if item.kind == "image" else VIDEO_LIMIT
        if not 0 < size <= limit:
            return self._skip(key, item, "too_large")
        path = self._library.path_for(item)
        version = json.dumps(list(item.version))
        known = self._ledger.published(key)
        digest = str(known["sha256"]) if known is not None and known["version"] == version else ""
        if not digest:
            with open_scoped(self.root, path) as stream:
                digest = checked_digest(stream, size_limit=limit)
        thumb = self._library.grid_preview(item, cancel=cancel)
        if thumb is None or not thumb.ready or thumb.mime not in CONTENT_TYPES:
            return "pending"
        bodies: dict[str, _Body] = {
            "thumb_320": _Body(
                MediaVariant(hashlib.sha256(thumb.data).hexdigest(), len(thumb.data), thumb.mime),
                data=thumb.data,
            ),
            "original": _Body(
                MediaVariant(digest, size, item.mime, item.width, item.height), path=path
            ),
        }
        with self._extra_bodies(item, path, cancel, allow_transcode) as extra:
            bodies.update(extra)
            created = datetime.fromtimestamp(item.effective_time / 1_000_000, UTC)
            manifest = item_manifest(
                item=ItemRef(key, digest),
                kind=item.kind,
                run_id=run_id_for(item.path, created),
                created_at=created,
                media={name: body.variant for name, body in bodies.items()},
                duration_s=item.duration,
                display=_display(item),
                batch=self._batch(client, path),
            )
            # The file must still be the bytes the manifest names when the gateway records it.
            self._library.path_for(item)
            state, missing = client.post_manifest(manifest)
            if state == "incomplete":
                for body in bodies.values():
                    if cancel.is_set():
                        return "pending"
                    if body.variant.sha256 in missing:
                        self._send(client, body)
                state, _missing = client.post_manifest(manifest)
            if state not in ("ready", "purged"):
                return "pending"
        self._ledger.mark_published(
            key, version, item.path, digest, item.kind, "published", utc_text(self._now())
        )
        if item.kind == "image":
            self._ledger.set_rendition(key)
        return "published"

    @contextmanager
    def _extra_bodies(
        self,
        item: LibraryItem,
        path: Path,
        cancel: Event,
        allow_transcode: Callable[[], bool],
    ) -> Iterator[dict[str, _Body]]:
        extra: dict[str, _Body] = {}
        if item.kind == "image":
            with open_scoped(self.root, path) as stream:
                encoded = encode_preview_1080(stream, item.mime)
            if encoded is not None:
                data, content_type, width, height = encoded
                extra["preview_1080"] = _Body(
                    MediaVariant(
                        hashlib.sha256(data).hexdigest(), len(data), content_type, width, height
                    ),
                    data=data,
                )
            yield extra
            return
        direct = item.mime in ("video/mp4", "video/webm") and item.version[2] <= MOBILE_DIRECT_LIMIT
        if direct or self._transcode is None or not allow_transcode():
            yield extra
            return
        with tempfile.TemporaryDirectory(prefix="stablenew-gateway-") as scratch:
            target = Path(scratch) / "mobile.mp4"
            with open_scoped(self.root, path) as source:
                made = self._transcode(source, target, cancel.is_set)
            if made and not cancel.is_set():
                with target.open("rb") as stream:
                    mobile_digest = checked_digest(stream, size_limit=VIDEO_LIMIT)
                size = target.stat().st_size
                extra["mobile_video"] = _Body(
                    MediaVariant(mobile_digest, size, "video/mp4"), path=target
                )
            yield extra

    def _send(self, client: GatewayClient, body: _Body) -> None:
        variant = body.variant
        if body.data is not None:
            client.upload_media(variant.sha256, body.data, variant.size)
            return
        assert body.path is not None
        if body.path.is_relative_to(self.root):
            with open_scoped(self.root, body.path) as stream:
                if os.fstat(stream.fileno()).st_size != variant.size:
                    raise SiteOutputError("media_changed")
                client.upload_media(variant.sha256, stream, variant.size)
            return
        with body.path.open("rb") as stream:
            client.upload_media(variant.sha256, stream, variant.size)
