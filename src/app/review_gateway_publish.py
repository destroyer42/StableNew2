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
import sqlite3
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
from src.app.review_gateway_origin import InputOf
from src.app.review_gateway_protocol import (
    CONTENT_TYPES,
    RUN_ID,
    ItemRef,
    MediaVariant,
    item_manifest,
    utc_text,
)
from src.app.review_gateway_scrub import Unclean, scrub_image
from src.app.review_gateway_sources import (
    NOT_OUTPUT,
    RETAINED,
    SourceFilter,
    may_be_unrecorded_frame,
)
from src.app.review_gateway_store import SyncLedger
from src.app.site_library_reconcile import key_for
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
#: The one-time withdrawal of frames published earlier: ledger rows per request, and requests per pass.
WITHDRAW_PAGE = 500
WITHDRAW_PAGES = 10
#: Ledger keys of that sweep. They are renamed when the source filter excludes more (RG-170: eval outputs), so a PC
#: that already swept looks through its ledger once again.
_SWEEP_DONE = "sources_withdrawn_v3"
_SWEEP_CURSOR = "sources_withdraw_cursor_v3"
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


#: Top output folder (casefolded) -> the phone's review section. A folder not listed is "other".
_SECTION_OF_FOLDER = {
    "pipeline": "pipeline",
    "learning": "learning",
    "reprocess": "reprocess",
    "testing": "testing",
    "movie_clips": "video",
    "svd": "video",
    "animatediff": "video",
}


def source_of(rel_path: str, kind: str) -> str:
    """The phone's review section for an output: learning runs stay together, every other video is a movie clip,
    and an image goes by its output route. Only this category id leaves the PC."""

    parts = Path(rel_path).parts
    folder = parts[0].casefold() if len(parts) > 1 else ""
    section = _SECTION_OF_FOLDER.get(folder, "other")
    if kind == "video" and section != "learning":
        return "video"
    return section


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


#: Drop every container, stream and chapter tag (PHONE-FAST): StableNew videos carry the workflow description and PC
#: paths there. Bit-exact, so the same file always gives the same bytes.
_NO_METADATA = ("-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact")


def ffmpeg_strip_metadata(source: BinaryIO, target: Path, cancelled: Callable[[], bool]) -> bool:
    """A copy of the video's picture and sound, not re-encoded, without any metadata; ``False`` when FFmpeg is absent
    or fails. The PC's own file is only read."""

    from src.pipeline.video import resolve_ffmpeg_executable
    from src.utils.managed_process import run_bounded

    tool = resolve_ffmpeg_executable()
    if tool is None:
        return False
    faststart = ["-movflags", "+faststart"] if target.suffix in (".mp4", ".mov") else []
    source.seek(0)
    outcome = run_bounded(
        [
            str(tool),
            *site_library_video.INPUT_OPTIONS,
            "-nostdin",
            "-i",
            "fd:",
            "-map",
            "0:V",
            "-map",
            "0:a?",
            "-c",
            "copy",
            *_NO_METADATA,
            *faststart,
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
            *_NO_METADATA,
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
#: NAME-INFO: ``(file, library item) -> info fields`` for the manifest.
InfoOf = Callable[[Path, LibraryItem], Mapping[str, Any]]


def image_source_job(path: Path) -> str:
    """The job id an image's embedded metadata names (``""`` when none or unreadable)."""

    from src.review.review_evidence import image_source_job as read

    try:
        return read(path)
    except Exception:  # noqa: BLE001 - lineage is extra; it must never hold publishing back
        log.debug("Review gateway publish could not read an item's job")
        return ""


def job_info_reader(repository: Any, identity: Callable[[Any], Mapping[str, Any] | None]) -> InfoOf:
    """NAME-INFO: what "More info" shows for a library item (``src/review/output_info.py``), read only."""

    from src.review.output_info import OutputDescriber

    describer = OutputDescriber(repository, batch_identity=identity)

    def read(path: Path, item: LibraryItem) -> Mapping[str, Any]:
        info = describer.describe(
            path,
            kind=item.kind,
            made_at=datetime.fromtimestamp(item.effective_time / 1_000_000, UTC),
            model=item.model or "",
            workflow=item.workflow or "",
            seed=item.seed,
        )
        # The name only, for Immich; the manifest keeps it only when it follows the descriptive scheme.
        return {**info, "file_name": path.name}

    return read


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
        from src.review.review_lineage import batch_of_job_reader

        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            return None
        try:
            job_id = (job_id_of or image_source_job)(path)
            batch = batch_of_job_reader(repository, identity)(job_id) if job_id else None
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
        input_of: InputOf | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        strip: Transcode = ffmpeg_strip_metadata,
        info_of: InfoOf | None = None,
    ) -> None:
        self._library = library
        self._ledger = ledger
        self._transcode = transcode
        self._now = now
        self._batch_of = batch_of
        self._info_of = info_of
        self._input_of = input_of
        self._sources = SourceFilter(library.root)
        self._monotonic = monotonic
        self._strip = strip
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

    def _info(
        self, client: GatewayClient, path: Path, item: LibraryItem
    ) -> Mapping[str, Any] | None:
        """The item's "More info", only for a gateway that takes it (an older one's schema refuses the field)."""

        if self._info_of is None or "item_info" not in client.features:
            return None
        try:
            info = dict(self._info_of(path, item))
        except Exception:  # noqa: BLE001 - display only; it must never hold publishing back
            log.debug("Review gateway publish could not describe an item")
            return None
        # A gateway that knows ``info`` but not the file name would refuse the whole manifest.
        if "item_file_name" not in client.features:
            info.pop("file_name", None)
        return info

    def _parent(self, key: str, item: LibraryItem, path: Path) -> tuple[str, str] | None:
        """The original a phone rework made this image from, recorded in the ledger as its lineage; named as the
        gateway knows it, which is by the bytes that were sent."""

        if item.kind != "image" or not self._ledger.has_rework():
            return None
        original = self._ledger.rework_original(image_source_job(path))
        if original is None or original[0] == key:
            return None
        self._ledger.remember_result(key, *original)
        library_id, file_sha = original
        sent = self._ledger.published(library_id)
        if sent is not None and self._ledger.file_digest(library_id, sent["sha256"]) == file_sha:
            return library_id, str(sent["sha256"])
        return original

    def _made_from(self, key: str, input_path: str) -> tuple[str, str] | None:
        """The Output Library item an input image is, matched by the SHA-256 of its bytes: ``(library_id, sha256 as
        the gateway knows it)``. A file that is gone is matched by where it was."""

        if not input_path:
            return None
        source = Path(os.path.abspath(input_path))
        try:
            rel = source.relative_to(self.root).as_posix()
        except ValueError:
            rel = ""
        known = None
        try:
            if source.is_file():
                with source.open("rb") as stream:
                    digest = checked_digest(stream, size_limit=IMAGE_LIMIT)
                known = self._ledger.sent_image(digest)
                # In the library but not sent (yet): the gateway shows it once it has it.
                if known is None and rel and self._library.store.get(key_for(rel)) is not None:
                    known = key_for(rel), digest
            elif rel and (row := self._ledger.published(key_for(rel))) is not None:
                known = key_for(rel), str(row["sha256"])
        except (OSError, SiteOutputError):
            log.debug("Review gateway publish could not match an input image")
        return known if known is not None and known[0] != key else None

    def _input(
        self, client: GatewayClient, key: str, item: LibraryItem, path: Path
    ) -> tuple[ItemRef | None, bool]:
        """``(the item an image was made from, whether it had an input that cannot be found)``."""

        if self._input_of is None or item.kind != "image" or "item_input" not in client.features:
            return None, False
        input_path = self._input_of(path)
        if input_path is None:
            return None, False
        found = self._made_from(key, input_path)
        return (ItemRef(*found), False) if found else (None, True)

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

    def _retry(self, known: sqlite3.Row) -> bool:
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

    def withdraw_unpublishable(self, client: GatewayClient, cancel: Event) -> None:
        """Once per ledger: ask the gateway to stop showing eval outputs, frames, un-smoothed clips and working files
        published earlier. A file that is merely outside the job output folders stays.

        Kept in steps, so a stop or an unreachable gateway resumes where it was.
        """

        if "item_withdraw" not in client.features or not self.root.is_dir():
            return
        if self._ledger.get_meta(_SWEEP_DONE) == "done":
            return
        cursor = int(self._ledger.get_meta(_SWEEP_CURSOR) or 0)
        for _ in range(WITHDRAW_PAGES):
            if cancel.is_set():
                return
            rows = self._ledger.published_after(cursor, WITHDRAW_PAGE)
            if not rows:
                self._ledger.set_meta({_SWEEP_DONE: "done"})
                return
            unwanted = [
                str(row["library_id"])
                for row in rows
                if self._sources.exclusion_of(str(row["rel_path"]), str(row["kind"]))
                not in ("", NOT_OUTPUT)
            ]
            if unwanted and not client.withdraw_items(unwanted):
                log.info("Review gateway did not accept the withdrawal of earlier items")
                return
            cursor = int(rows[-1]["rowid"])
            self._ledger.set_meta({_SWEEP_CURSOR: str(cursor)})

    def label_published(self, client: GatewayClient, cancel: Event) -> None:
        """Once per ledger: tell the gateway the sections of items published before it kept them. Resumes like
        ``withdraw_unpublishable``."""

        if "item_source" not in client.features:
            return
        if self._ledger.get_meta("sections_labelled") == "done":
            return
        cursor = int(self._ledger.get_meta("sections_label_cursor") or 0)
        for _ in range(WITHDRAW_PAGES):
            if cancel.is_set():
                return
            rows = self._ledger.published_after(cursor, WITHDRAW_PAGE)
            if not rows:
                self._ledger.set_meta({"sections_labelled": "done"})
                return
            named = [
                (str(row["library_id"]), source_of(str(row["rel_path"]), str(row["kind"])))
                for row in rows
            ]
            if not client.label_items(named):
                log.info("Review gateway did not accept the sections of earlier items")
                return
            cursor = int(rows[-1]["rowid"])
            self._ledger.set_meta({"sections_label_cursor": str(cursor)})

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
            self._add_inputs(client, limit - len(rows), cancel, result)
        return result

    def _add_inputs(
        self, client: GatewayClient, limit: int, cancel: Event, result: PublishResult
    ) -> None:
        """Images published before inputs were linked: those made from one are sent again, a few at a time when
        idle, so the gateway can show them side by side."""

        if self._input_of is None or "item_input" not in client.features:
            return
        for key in self._ledger.without_input_check(limit):
            if cancel.is_set():
                return
            item = self._unchanged_item(key)
            if item is None or self._input_of(self.root / item.path) is None:
                self._ledger.set_input_checked(key)
                continue
            try:
                state = self._publish_one(client, key, item, cancel, lambda: False)
            except (GatewayConflict, GatewayRejected, SiteOutputError, OSError):
                self._ledger.set_input_checked(key)  # it stays as published, shown alone
                continue
            if state == "published":
                result.published += 1

    def _unchanged_item(self, key: str) -> LibraryItem | None:
        """The library item behind a published row, while it is still the file that was sent and may be sent."""

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
            return None
        return item

    def _add_renditions(
        self, client: GatewayClient, limit: int, cancel: Event, result: PublishResult
    ) -> None:
        """Images published before every image had a phone rendition are sent again, a few at a time when idle.

        Only ever adds: a row that is gone, changed or now excluded is marked done and stays as it was.
        """

        for key in self._ledger.without_rendition(limit):
            if cancel.is_set():
                return
            item = self._unchanged_item(key)
            if item is None:
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
        if digest:
            digest = self._ledger.file_digest(key, digest)
        if not digest:
            with open_scoped(self.root, path) as stream:
                digest = checked_digest(stream, size_limit=limit)
        thumb = self._library.grid_preview(item, cancel=cancel)
        if thumb is None or not thumb.ready or thumb.mime not in CONTENT_TYPES:
            return "pending"
        # An image already sent as it is stays that item: a second copy of it would be a second item.
        as_before = (
            item.kind == "image"
            and known is not None
            and known["state"] == "published"
            and known["version"] == version
            and known["sha256"] == digest
        )
        with (
            self._original(item, path, digest, size, cancel, as_before) as original,
            self._extra_bodies(item, path, cancel, allow_transcode) as extra,
        ):
            if original is None:
                return "pending"  # a video that cannot be stripped never leaves the PC
            file_digest = digest
            digest = original.variant.sha256
            bodies: dict[str, _Body] = {
                "thumb_320": _Body(
                    MediaVariant(
                        hashlib.sha256(thumb.data).hexdigest(), len(thumb.data), thumb.mime
                    ),
                    data=thumb.data,
                ),
                "original": original,
                **extra,
            }
            created = datetime.fromtimestamp(item.effective_time / 1_000_000, UTC)
            parent = self._parent(key, item, path)
            # A phone rework already names its original; anything else may name the input it was made from.
            made_from, missing_input = (
                (None, False) if parent else self._input(client, key, item, path)
            )
            manifest = item_manifest(
                item=ItemRef(key, digest),
                kind=item.kind,
                run_id=run_id_for(item.path, created),
                created_at=created,
                media={name: body.variant for name, body in bodies.items()},
                duration_s=item.duration,
                display=_display(item),
                batch=self._batch(client, path),
                # Only for a gateway that takes it: an older one's schema refuses the field.
                parent=ItemRef(*parent) if parent and "item_parent" in client.features else None,
                source=source_of(item.path, item.kind) if "item_source" in client.features else "",
                made_from=made_from,
                made_from_missing=missing_input,
                info=self._info(client, path, item),
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
        if digest != file_digest:
            self._ledger.set_public_digest(key, digest, file_digest)
        self._ledger.mark_published(
            key, version, item.path, digest, item.kind, "published", utc_text(self._now())
        )
        if item.kind == "image":
            self._ledger.set_rendition(key)
            if "item_input" in client.features:
                self._ledger.set_input_checked(key)
        return "published"

    @contextmanager
    def _original(
        self,
        item: LibraryItem,
        path: Path,
        digest: str,
        size: int,
        cancel: Event,
        as_before: bool,
    ) -> Iterator[_Body | None]:
        """What is sent as the original, without PC paths in its metadata (``None`` when that cannot be assured, so it
        is not sent at all): an image keeps its other metadata, a video loses all of it. The item is known to the
        gateway by the bytes sent."""

        unchanged = _Body(MediaVariant(digest, size, item.mime, item.width, item.height), path=path)
        if item.kind != "video":
            if as_before:
                yield unchanged
                return
            with open_scoped(self.root, path) as stream:
                data = stream.read(IMAGE_LIMIT + 1)
            try:
                clean = scrub_image(data)
            except Unclean:
                log.warning(
                    "Review gateway: an image was not sent; its metadata could not be cleaned"
                )
                yield None
                return
            if clean is data:
                yield unchanged
                return
            yield _Body(
                MediaVariant(
                    hashlib.sha256(clean).hexdigest(),
                    len(clean),
                    item.mime,
                    item.width,
                    item.height,
                ),
                data=clean,
            )
            return
        with tempfile.TemporaryDirectory(prefix="stablenew-gateway-") as scratch:
            target = Path(scratch) / f"original{path.suffix.lower()}"
            with open_scoped(self.root, path) as source:
                made = self._strip(source, target, cancel.is_set)
            if not made or cancel.is_set():
                if not cancel.is_set():
                    log.warning(
                        "Review gateway: a video was not sent; its metadata could not be removed"
                    )
                yield None
                return
            with target.open("rb") as stream:
                sent = checked_digest(stream, size_limit=VIDEO_LIMIT)
            length = target.stat().st_size
            yield _Body(MediaVariant(sent, length, item.mime, item.width, item.height), path=target)

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
