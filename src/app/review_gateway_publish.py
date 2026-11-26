"""Publish Output Library items to the review gateway (RG-120).

The source is the Output Library index (``src/app/site_library_index.py``): its own rebuildable SQLite cache, never the
job database. Each item crosses the boundary as a manifest naming its library id and SHA-256 plus media bodies
addressed by their own SHA-256; no path, file name or folder ever leaves the PC (RG-100 invariant 3). Publishing is
idempotent by SHA-256 (the manifest goes first and the gateway names the bodies it still lacks, so a body it already
holds is not sent again; an unchanged item is skipped from the ledger) and resumable (the ledger records an item only
once the gateway reports it ready).

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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
from src.app.review_gateway_store import SyncLedger
from src.app.site_media_files import SiteOutputError, checked_digest, open_scoped
from src.app.site_output_library import LibraryItem, OutputLibrary
from src.app.site_video_playback import VIDEO_LIMIT
from src.state.output_routing import ARCHIVE_DIR_NAME

log = logging.getLogger(__name__)

IMAGE_LIMIT = 64 * 1024 * 1024
PREVIEW_EDGE = 1080
#: A clip at or under this size, already MP4/WebM, is played on the phone from its original (no transcode).
MOBILE_DIRECT_LIMIT = 64 * 1024 * 1024
MOBILE_EDGE = 1280
#: Only items this recent (relative to when the gateway was first configured) are published.
BACKFILL_DAYS = 3
_SKIPPED_FOLDERS = (ARCHIVE_DIR_NAME, ".stablenew-library")
_RUN_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_SEED = re.compile(r"-?[0-9]{1,19}")
_PROMPT_EXCERPT = 240

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
    """A 1080 px (long edge) WebP, or JPEG when WebP is unavailable; ``None`` when not needed or not decodable."""

    try:
        with Image.open(stream) as image:
            if image.width * image.height > site_library_video.MAX_PIXELS:
                return None
            if max(image.width, image.height) <= PREVIEW_EDGE:
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


class GatewayPublisher:
    def __init__(
        self,
        library: OutputLibrary,
        ledger: SyncLedger,
        *,
        transcode: Transcode | None = ffmpeg_mobile_transcode,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._library = library
        self._ledger = ledger
        self._transcode = transcode
        self._now = now

    @property
    def root(self) -> Path:
        return self._library.root

    def publish_since(self) -> int:
        """Microseconds since the epoch; fixed the first time the worker publishes."""

        stored = self._ledger.get_meta("publish_since")
        if stored.isdigit():
            return int(stored)
        since = int((self._now().timestamp() - BACKFILL_DAYS * 86400) * 1_000_000)
        self._ledger.set_meta({"publish_since": str(since)})
        return since

    def candidates(self, limit: int) -> list[tuple[str, LibraryItem]]:
        """Up to ``limit`` unpublished (or changed) index rows, newest first."""

        self._library.start()
        since = self.publish_since()
        found: list[tuple[str, LibraryItem]] = []
        offset = 0
        while len(found) < limit:
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
            for row in rows:
                known = self._ledger.published(row["key"])
                if known is not None and known["version"] == row["version"]:
                    continue
                item = LibraryItem.from_row(row)
                found.append((str(row["key"]), item))
                if len(found) >= limit:
                    break
        return found

    def publish(
        self,
        client: GatewayClient,
        *,
        limit: int,
        cancel: Event,
        allow_transcode: Callable[[], bool] = lambda: True,
    ) -> PublishResult:
        result = PublishResult()
        for key, item in self.candidates(limit):
            if cancel.is_set():
                break
            try:
                state = self._publish_one(client, key, item, cancel, allow_transcode)
            except (GatewayConflict, GatewayRejected):
                result.pending += 1
                continue
            except (SiteOutputError, OSError):
                log.debug("Review gateway publish deferred an item that changed or is unreadable")
                result.pending += 1
                continue
            if state == "published":
                result.published += 1
            elif state == "pending":
                result.pending += 1
            else:
                result.skipped += 1
        return result

    def _skip(self, key: str, item: LibraryItem, state: str) -> str:
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
