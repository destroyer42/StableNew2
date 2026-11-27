"""PC side of RG-170: registered rating sets to the review gateway, submitted ratings back into the eval's files.

The sync worker calls ``RatingTaskSync.step`` on its own thread; everything here is blocking file and network work,
never Tk. Outbound only (RG-100 invariant 1). The registration folder and the eval's files are the authorities; what is
kept beside them (``state/``, ``cache/``) can be deleted and is rebuilt.

**Out.** Each registered set (``src/video/video_eval_rating_task.py``) becomes a ``rating_task``: ids, text and media
addressed by SHA-256. Paths, case ids, key files and file names stay here. Every clip is re-encoded the same way with
its container metadata dropped (StableNew clips carry their workflow, backend and a PC path there, which would also
break the blinding) and every picture is re-saved without metadata. Nothing is transcoded while a job runs.

**Back.** A submission is untrusted input: it must come from a phone this PC paired, not revoked, with the ``review``
scope, and its answers are checked again before ``apply_answers`` writes the eval's own contract. The outcome is saved
before it is acknowledged, so a repeated submission gets the same answer and is never applied twice.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from src.app.review_gateway_client import (
    GatewayClient,
    GatewayConflict,
    GatewayError,
    GatewayRejected,
)
from src.app.review_gateway_protocol import SCHEMA_VERSION, utc_now, utc_text
from src.app.review_gateway_store import SyncLedger, _local_state_dir
from src.utils.atomic_io import atomic_write_bytes
from src.video.video_eval_rating_task import (
    RatingConflict,
    RatingSpec,
    apply_answers,
    check_clip_identity,
    file_digest,
    follow_up_spec,
    is_rated,
    load_rating_specs,
    register_rating_task,
)

log = logging.getLogger(__name__)

FEATURE = "rating_tasks"
#: An unchanged set is sent again this often, which repairs a gateway that lost its data.
HEARTBEAT_SECONDS = 600.0
#: A cycle encodes at most this many clips, so a large sitting never holds phone decisions back for long.
ENCODES_PER_CYCLE = 4
MOBILE_EDGE = 1280
#: Near lossless: the owner is judging these clips, so the phone copy must not add artifacts of its own.
RATING_CRF = 18
DESK_NOTE = "Rated on the PC."
_RENDITION = "r1"
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_TASK_ID = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

VideoEncoder = Callable[[Path, Path, Callable[[], bool]], bool]


def default_rating_folder() -> Path:
    """Where a harness registers a sitting: beside the sync ledger, shared by every checkout on this PC."""

    return _local_state_dir() / "rating_tasks"


def encode_rating_video(source: Path, target: Path, cancelled: Callable[[], bool]) -> bool:
    """H.264/AAC MP4 at most 1280 px with no metadata or chapters; ``False`` when FFmpeg is absent or fails.

    Every clip of every sitting goes through this same encode, so no arm is treated differently.
    """

    from src.app import site_library_video
    from src.pipeline.video import resolve_ffmpeg_executable
    from src.utils import managed_process

    tool = resolve_ffmpeg_executable()
    if tool is None:
        return False
    scale = (
        f"scale=w='min(iw,{MOBILE_EDGE})':h='min(ih,{MOBILE_EDGE})'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    with source.open("rb") as stream:
        outcome = managed_process.run_bounded(
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
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-vf",
                scale,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                str(RATING_CRF),
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-fflags",
                "+bitexact",
                "-flags:v",
                "+bitexact",
                "-movflags",
                "+faststart",
                "-y",
                str(target),
            ],
            timeout_seconds=600,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=4096,
            stdin_file=stream,
            below_normal=True,
            cancel=cancelled,
            memory_limit_mb=1024,
            allow_unenforced_memory_limit=True,
        )
    return outcome.returncode == 0 and target.is_file() and target.stat().st_size > 0


def encode_rating_image(source: Path, target: Path) -> bool:
    """A WebP at most 1280 px on the long edge with none of the source's metadata."""

    try:
        with Image.open(source) as image:
            picture = ImageOps.exif_transpose(image).convert("RGB")
        picture.thumbnail((MOBILE_EDGE, MOBILE_EDGE))
        # A fresh image carries no text chunks, EXIF or profile.
        clean = Image.new("RGB", picture.size)
        clean.paste(picture)
        clean.save(target, "WEBP", quality=90)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return False
    return True


class _Waiting(Exception):
    """A rendition is not ready yet (a job is running, or this cycle's encodes are used up)."""


class RatingTaskSync:
    def __init__(
        self,
        folder: Path,
        ledger: SyncLedger,
        *,
        video_encoder: VideoEncoder = encode_rating_video,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.folder = Path(folder)
        self._ledger = ledger
        self._video_encoder = video_encoder
        self._monotonic = monotonic
        #: ``task id -> (registration bytes digest, when it was last sent)``; empty after a restart, so all are sent.
        self._sent: dict[str, tuple[str, float]] = {}
        self._encodes_left = 0

    def step(self, client: GatewayClient, *, busy: bool, cancel: Event) -> None:
        """Apply submitted ratings, then send what changed. Gateway outages propagate to the sync worker."""

        if FEATURE not in client.features:
            return
        if not self.folder.is_dir():
            return
        specs = {spec.task_id: spec for _path, spec, _error in self._load() if spec is not None}
        self._apply(client, specs, cancel)
        # Applying may have registered a follow-up.
        entries = self._load()
        self._encodes_left = ENCODES_PER_CYCLE
        for path, spec, _error in entries:
            if cancel.is_set():
                return
            if spec is None:
                continue
            try:
                self._publish(client, path, spec, busy, cancel)
            except _Waiting:
                continue
            except RatingConflict as error:
                log.warning("Rating set %s is not published (%s)", spec.task_id, error.reason)
            except (GatewayConflict, GatewayRejected):
                log.warning("The review gateway refused rating set %s", spec.task_id)
            except (OSError, ValueError) as error:
                # Type only: a message may carry a path.
                log.warning(
                    "Rating set %s is not published (%s)", spec.task_id, type(error).__name__
                )
        self._withdraw(client, {path.stem for path, _spec, _error in entries})

    def _load(self) -> list[tuple[Path, RatingSpec | None, str]]:
        return load_rating_specs(self.folder)

    # -- per-task state -----------------------------------------------------------------------------------------

    def _state_path(self, task_id: str) -> Path:
        return self.folder / "state" / f"{task_id}.json"

    def _state(self, task_id: str) -> dict[str, Any]:
        try:
            value = json.loads(self._state_path(task_id).read_bytes())
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_state(self, task_id: str, **changes: Any) -> None:
        path = self._state_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {**self._state(task_id), **changes}
        atomic_write_bytes(path, json.dumps(document, indent=1).encode("utf-8"))

    # -- out ----------------------------------------------------------------------------------------------------

    def _rendition(self, source: Path, busy: bool, cancel: Event) -> tuple[Path, dict[str, Any]]:
        """The cached phone copy of one file and its ``media_variant``."""

        info = source.stat()
        image = source.suffix.lower() in _IMAGE_SUFFIXES
        name = hashlib.sha256(
            f"{_RENDITION}|{source}|{info.st_size}|{info.st_mtime_ns}".encode()
        ).hexdigest()
        target = self.folder / "cache" / f"{name}{'.webp' if image else '.mp4'}"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f"part-{target.name}")
            try:
                if image:
                    made = encode_rating_image(source, partial)
                else:
                    if busy or self._encodes_left <= 0:
                        raise _Waiting
                    self._encodes_left -= 1
                    made = self._video_encoder(source, partial, cancel.is_set)
                if cancel.is_set():
                    raise _Waiting
                if not made:
                    raise OSError("the phone copy could not be made")
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)
        variant = {
            "sha256": file_digest(target),
            "bytes": target.stat().st_size,
            "content_type": "image/webp" if image else "video/mp4",
        }
        return target, variant

    def _manifest(
        self, spec: RatingSpec, busy: bool, cancel: Event
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        """The ``rating_task`` for a set and ``{digest: cached file}``. Only ids, text and media leave."""

        files: dict[str, Path] = {}
        waiting = False

        def media(value: str) -> dict[str, Any] | None:
            nonlocal waiting
            try:
                target, variant = self._rendition(spec.path(value), busy, cancel)
            except _Waiting:
                waiting = True  # keep going: encode what this cycle still can
                return None
            files[variant["sha256"]] = target
            return variant

        items = []
        for item in spec.items:
            entry: dict[str, Any] = {
                k: item[k] for k in ("item_id", "title", "context") if item.get(k)
            }
            if item.get("reference"):
                entry["reference"] = media(item["reference"])
            entry["clips"] = [
                {"clip_id": c["clip_id"], "label": c["label"], "media": media(c["path"])}
                for c in item.get("clips", [])
            ]
            items.append(entry)
        if waiting:
            raise _Waiting
        manifest = self._header(spec, "open")
        manifest["items"] = items
        return manifest, files

    @staticmethod
    def _header(spec: RatingSpec, state: str) -> dict[str, Any]:
        created = datetime.fromisoformat(str(spec.data["created_at"]).replace("Z", "+00:00"))
        header: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "type": "rating_task",
            "task_id": spec.task_id,
            "title": spec.data["title"],
            "kind": spec.kind,
            "state": state,
            "instructions": spec.data.get("instructions", ""),
            "created_at": utc_text(created if created.tzinfo else created.replace(tzinfo=UTC)),
            "criteria": spec.criteria,
        }
        if spec.data.get("follow_up_of"):
            header["follow_up_of"] = spec.data["follow_up_of"]
        return header

    def _publish(
        self, client: GatewayClient, path: Path, spec: RatingSpec, busy: bool, cancel: Event
    ) -> None:
        state = self._state(spec.task_id)
        if state.get("status") == "done":
            return
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sent = self._sent.get(spec.task_id)
        if sent and sent[0] == digest and self._monotonic() - sent[1] < HEARTBEAT_SECONDS:
            return
        if is_rated(spec):
            # Rated at the desk (or before): a phone that was shown it sees it done, otherwise it never appears.
            manifest = state.get("manifest")
            if manifest:
                client.post_rating_task({**manifest, "state": "done", "note": DESK_NOTE})
            self._save_state(spec.task_id, status="done")
            self._discard_renditions()
            return
        check_clip_identity(spec)
        manifest, files = self._manifest(spec, busy, cancel)
        status, missing = client.post_rating_task(manifest)
        if status == "incomplete":
            for name in sorted(missing):
                if cancel.is_set():
                    return
                target = files[name]
                with target.open("rb") as stream:
                    client.upload_rating_media(name, stream, target.stat().st_size)
            status, _missing = client.post_rating_task(manifest)
        if status != "ready":
            return
        self._sent[spec.task_id] = (digest, self._monotonic())
        renditions = sorted({target.name for target in files.values()})
        self._save_state(spec.task_id, status="open", manifest=manifest, renditions=renditions)

    def _withdraw(self, client: GatewayClient, registered: set[str]) -> None:
        """A removed registration leaves the phone."""

        for path in (self.folder / "state").glob("*.json"):
            task_id = path.stem
            state = self._state(task_id)
            if task_id in registered or state.get("status") != "open" or not state.get("manifest"):
                continue
            try:
                client.post_rating_task({**state["manifest"], "state": "withdrawn"})
            except (GatewayConflict, GatewayRejected):
                log.warning("The review gateway refused to withdraw rating set %s", task_id)
                continue
            self._sent.pop(task_id, None)
            self._save_state(task_id, status="withdrawn")
            self._discard_renditions()

    def _discard_renditions(self) -> None:
        """The phone copies are private content: keep only those an open set still uses."""

        wanted: set[str] = set()
        for path in (self.folder / "state").glob("*.json"):
            state = self._state(path.stem)
            if state.get("status") == "open":
                wanted.update(state.get("renditions", []))
        for path in (self.folder / "cache").glob("*"):
            if path.name not in wanted:
                path.unlink(missing_ok=True)

    # -- back ---------------------------------------------------------------------------------------------------

    def _apply(self, client: GatewayClient, specs: Mapping[str, RatingSpec], cancel: Event) -> None:
        for raw in client.rating_submissions():
            if cancel.is_set():
                return
            if not isinstance(raw, dict):
                continue
            submission_id, task_id = raw.get("submission_id"), raw.get("task_id")
            if not (isinstance(submission_id, str) and _UUID.fullmatch(submission_id)):
                continue  # nothing to acknowledge
            if not (isinstance(task_id, str) and _TASK_ID.fullmatch(task_id)):
                client.acknowledge_rating(_acknowledgement(submission_id, "invalid_record"))
                continue
            done = self._state(task_id).get("submissions", {}).get(submission_id)
            if done is None:
                done = self._outcome(raw, specs.get(task_id), task_id)
                if done is None:
                    continue  # not decidable now: it stays pending and is asked again
                outcomes = {**self._state(task_id).get("submissions", {}), submission_id: done}
                if done["reason"]:
                    self._save_state(task_id, submissions=outcomes)
                    self._sent.pop(task_id, None)
                else:
                    self._save_state(task_id, status="done", submissions=outcomes)
                    self._discard_renditions()
                log.info(
                    "Phone ratings for %s: %s",
                    task_id,
                    done["reason"] or "written to the eval files",
                )
            client.acknowledge_rating(
                _acknowledgement(submission_id, done["reason"], done["reveal"])
            )

    def _outcome(
        self, raw: Mapping[str, Any], spec: RatingSpec | None, task_id: str
    ) -> dict[str, Any] | None:
        def refused(reason: str) -> dict[str, Any]:
            return {"reason": reason, "reveal": []}

        device_id = raw.get("device_id")
        device = self._ledger.device(device_id) if isinstance(device_id, str) else None
        if device is None or device.revoked:
            return refused("revoked_device")
        if "review" not in device.scopes:
            return refused("not_granted")
        if spec is None:
            # A file that is there but unreadable is waited for; a removed one is refused.
            return None if (self.folder / f"{task_id}.json").exists() else refused("unknown_task")
        try:
            reveal = apply_answers(spec, raw.get("answers"))
        except RatingConflict as error:
            return refused(error.reason)
        except OSError:
            log.warning("Phone ratings for %s are waiting for the eval files", task_id)
            return None
        follow = follow_up_spec(spec, reveal)
        if follow is not None:
            try:
                register_rating_task(follow, self.folder)
            except (OSError, ValueError):
                log.warning("The follow-up question for %s could not be registered", task_id)
        return {"reason": "", "reveal": reveal}


def _acknowledgement(
    submission_id: str, reason: str, reveal: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "rating_acknowledgement",
        "submission_id": submission_id,
        "outcome": "refused" if reason else "applied",
        "acknowledged_at": utc_text(utc_now()),
    }
    if reason:
        payload["reason_code"] = reason
    elif reveal:
        payload["reveal"] = reveal
    return payload


__all__ = [
    "FEATURE",
    "HEARTBEAT_SECONDS",
    "GatewayError",
    "RatingTaskSync",
    "default_rating_folder",
    "encode_rating_image",
    "encode_rating_video",
]
