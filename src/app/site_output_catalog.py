"""Read-only projection of eval reports and exact media from an operator-approved output root."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any
from weakref import ref

from src.app.site_media_files import MEDIA_TYPES, checked_digest, inside, open_scoped
from src.app.site_media_files import SiteOutputError as SiteOutputError
from src.app.site_native_review import NativeImageReview
from src.app.site_output_library import OutputLibrary
from src.app.site_rating_sync import edit_stamp, field_conflicts, root_identity, was_applied
from src.app.site_video_playback import VIDEO_LIMIT, VideoPlayback
from src.video.video_eval_catalog import RUN_ID_PATTERN, list_run_ids
from src.video.video_eval_ratings_store import (
    ARTIFACT_COLUMN,
    CONTEXT_COLUMN,
    KEY_COLUMNS,
    MAX_RATINGS_BYTES,
    MOTION_RATING_COLUMNS,
    RATING_COLUMNS,
    RUBRIC_COLUMN,
    LoadedRatings,
    RatingsFileError,
    load_ratings,
    output_header,
    render_csv,
    write_ratings,
)
from src.video.video_eval_rubric import (
    ACTION_COLUMN,
    MOTION_COLUMNS,
    MOTION_RUBRIC_VERSION,
    parse_rating_row,
    row_has_content,
    row_has_motion_content,
)
from src.video.video_eval_run import EVAL_OUTPUT_FOLDER, RUN_MANIFEST_NAME, RUN_SCHEMA

_REPORT_SCHEMA = "stablenew.video-eval-report.v1"
_DIGEST = re.compile(r"[a-f0-9]{64}")
_MAX_REPORT = 5 * 1024 * 1024
_MAX_MEDIA = 64 * 1024 * 1024
_MAX_CELLS = 500
_JUDGMENTS = set(RATING_COLUMNS) - {*KEY_COLUMNS, ARTIFACT_COLUMN}
_MOTION_JUDGMENTS = frozenset(MOTION_COLUMNS)
_ALL_JUDGMENTS = _JUDGMENTS | _MOTION_JUDGMENTS
_MOTION_REVIEW_FIELDS = _MOTION_JUDGMENTS | {ACTION_COLUMN}
_RECEIPTS_COLUMN = "site_rating_receipts"


@dataclass(frozen=True)
class _Asset:
    path: Path
    sha256: str
    mime: str
    run_id: str | None = None


def _bounded_json(root: Path, path: Path) -> dict[str, Any]:
    with open_scoped(root, path) as stream:
        raw = stream.read(_MAX_REPORT + 1)
    if len(raw) > _MAX_REPORT:
        raise SiteOutputError("report_too_large")
    content = json.loads(raw)
    if not isinstance(content, dict):
        raise SiteOutputError("invalid_report")
    return content


def _text(value: object, *, limit: int = 240) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _objects(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_CELLS:
        raise SiteOutputError("invalid_report")
    if not all(isinstance(item, dict) for item in value):
        raise SiteOutputError("invalid_report")
    return value


def _index(items: object, key: str) -> dict[str, dict[str, Any]]:
    result = {}
    for item in _objects(items):
        identity = _text(item.get(key))
        if not identity or identity in result:
            raise SiteOutputError("invalid_report")
        result[identity] = item
    return result


class SiteOutputCatalog:
    """One grant for one output root. Public identifiers never directly resolve paths."""

    def __init__(
        self,
        output_root: Path,
        *,
        active: Callable[[], bool] = lambda: True,
        review_outputs: Callable[[str], Sequence[str]] | None = None,
        review_records: Path | None = None,
        preview_idle: Callable[[], bool] = lambda: True,
    ) -> None:
        self._root = output_root.resolve(strict=True)
        if not self._root.is_dir():
            raise SiteOutputError("output_folder_required")
        self._root_identity = root_identity(self._root)
        self._lock = Lock()
        self._revoked = Event()
        self._active = active
        self.scope = secrets.token_hex(16)
        catalog_ref = ref(self)

        def require_active() -> None:
            catalog = catalog_ref()
            if catalog is None:
                raise SiteOutputError("output_folder_not_shared")
            catalog.require_active()

        self.library = OutputLibrary(self._root, self.scope, require_active, preview_idle)
        self.review_outputs = review_outputs
        self.native_review = (
            NativeImageReview(self.library, review_records) if review_records is not None else None
        )
        self.playback = VideoPlayback(self._root, self.require_active)
        self._media: dict[str, _Asset] = {}
        self._results: dict[str, _Asset] = {}

    def revoke(self) -> None:
        self._revoked.set()
        self.library.close()
        self.playback.close()

    def require_active(self) -> None:
        if self._revoked.is_set() or not self._active():
            raise SiteOutputError("output_folder_not_shared")
        try:
            matches = self._root_identity == root_identity(self._root)
        except OSError:
            matches = False
        if not matches:
            raise SiteOutputError("output_folder_changed")

    def _inside(self, path: Path) -> Path:
        return inside(self._root, path)

    def _report_paths(self, run_id: str) -> tuple[Path, Path]:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise SiteOutputError("unknown_run")
        directory = self._inside(self._root / EVAL_OUTPUT_FOLDER / run_id)
        return (
            self._inside(directory / RUN_MANIFEST_NAME),
            self._inside(directory / "metrics.json"),
        )

    def list_runs(self, *, include_unbuilt: bool = False) -> list[str]:
        return list_run_ids(
            self._root,
            include_unbuilt=include_unbuilt,
            resolve_path=self._inside,
            path_error=SiteOutputError,
        )

    def eval_manifest(self, run_id: str) -> tuple[Path, dict[str, Any]]:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise SiteOutputError("unknown_run")
        directory = self._inside(self._root / EVAL_OUTPUT_FOLDER / run_id)
        manifest = _bounded_json(self._root, directory / RUN_MANIFEST_NAME)
        if manifest.get("schema") != RUN_SCHEMA or manifest.get("run_id") != run_id:
            raise SiteOutputError("invalid_report")
        return directory, manifest

    def _register(
        self,
        path_value: object,
        digest: object,
        prefix: str,
        media: dict[str, _Asset],
        run_id: str | None = None,
    ) -> str | None:
        if not isinstance(path_value, str) or not isinstance(digest, str):
            return None
        if not _DIGEST.fullmatch(digest.lower()):
            return None
        path = Path(path_value)
        if not path.is_absolute():
            base = self._root if path.parts[0:1] != (self._root.name,) else self._root.parent
            path = base / path
        try:
            resolved = self._inside(path)
            mime = MEDIA_TYPES.get(resolved.suffix.lower(), "")
            if not mime.startswith(prefix) or not resolved.is_file():
                return None
        except (OSError, SiteOutputError):
            return None
        identifier = secrets.token_hex(16)
        media[identifier] = _Asset(resolved, digest.lower(), mime, run_id)
        return identifier

    def _run_data(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            manifest, metrics = (
                _bounded_json(self._root, path) for path in self._report_paths(run_id)
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SiteOutputError("report_unavailable") from exc
        if (
            manifest.get("schema") != RUN_SCHEMA
            or metrics.get("schema") != _REPORT_SCHEMA
            or manifest.get("run_id") != run_id
            or metrics.get("run_id") != run_id
        ):
            raise SiteOutputError("invalid_report")

        return manifest, metrics

    def get_run(self, run_id: str, *, review: bool = False) -> dict[str, Any]:
        manifest, metrics = self._run_data(run_id)
        cases = _index(manifest.get("cases"), "case_id")
        arms = _index(manifest.get("arms"), "arm_id")
        jobs = _index(manifest.get("jobs"), "job_id")
        cells = _index(metrics.get("cells"), "job_id")
        if not jobs or jobs.keys() != cells.keys():
            raise SiteOutputError("invalid_report")
        loaded = self._ratings(run_id) if review else None
        ratings = loaded.keyed() if loaded is not None else {}
        media: dict[str, _Asset] = {}
        rows = []
        assessment = metrics.get("identity_assessment")
        sources = assessment.get("sources") if isinstance(assessment, dict) else {}
        sources = sources if isinstance(sources, dict) else {}
        motion_evaluation = metrics.get("motion_evaluation")
        assessed_motion = (
            _index(assessment["cells"], "job_id")
            if review
            and isinstance(motion_evaluation, dict)
            and motion_evaluation.get("rubric_version") == MOTION_RUBRIC_VERSION
            and isinstance(assessment, dict)
            and isinstance(assessment.get("cells"), list)
            else {}
        )
        for identity, job in jobs.items():
            case_id, arm_id = _text(job.get("case_id")), _text(job.get("arm_id"))
            cell = cells[identity]
            if (
                case_id not in cases
                or arm_id not in arms
                or cell.get("case_id") != case_id
                or cell.get("arm_id") != arm_id
            ):
                raise SiteOutputError("invalid_report")
            case = cases[case_id]
            state = _text(cell.get("state"), limit=40)
            source = sources.get(case_id)
            source_hash = case.get("image_sha256") or (
                source.get("claimed_sha256") if isinstance(source, dict) else None
            )
            row: dict[str, Any] = {
                "case": case_id,
                "arm": _text(arms[arm_id].get("label")) or arm_id,
                "job_id": identity,
                "state": state,
                "review": _text(cell.get("assessment_state"), limit=40),
                "clip": self._register(
                    cell.get("path"), cell.get("artifact_sha256"), "video/", media, run_id
                )
                if state == "playable"
                else None,
                "source": self._register(case.get("image"), source_hash, "image/", media),
            }
            if review:
                saved = ratings.get((case_id, arm_id, identity))
                if saved is None:
                    raise SiteOutputError("ratings_unavailable")
                motion = self._motion_review(
                    job, case, cell, assessed_motion.get(identity, {}), media
                )
                cell_metrics = cell.get("metrics")
                duration = (
                    cell_metrics.get("duration_seconds") if isinstance(cell_metrics, dict) else None
                )
                row.update(
                    arm_id=arm_id,
                    workflow={
                        key: _text(overrides.get(key))
                        for key in ("workflow_id", "workflow_version")
                    }
                    if isinstance(overrides := arms[arm_id].get("overrides"), dict)
                    else {},
                    seed=job.get("seed") if type(job.get("seed")) is int else None,
                    frames=job.get("frame_count") if type(job.get("frame_count")) is int else None,
                    prompt=_text(case.get("prompt"), limit=8000),
                    source_sha256=_text(source_hash).lower(),
                    artifact_sha256=_text(cell.get("artifact_sha256")).lower(),
                    duration=duration if isinstance(duration, (float, int)) else None,
                    rating={
                        key: value
                        for key, value in saved.items()
                        if key in _JUDGMENTS
                        or key == ARTIFACT_COLUMN
                        or (motion is not None and key in MOTION_RATING_COLUMNS)
                    },
                )
                if motion is not None:
                    row["motion"] = motion
            rows.append(row)
        with self._lock:
            self._media.update(media)
            if len(self._media) > 4000:
                self._media = dict(list(self._media.items())[-3000:])
        result: dict[str, Any] = {"run_id": run_id, "clips": rows}
        if loaded is not None:
            revision = hashlib.sha256(loaded.raw or b"").hexdigest()
            measured_revision = _text(metrics.get("ratings_revision"))
            result.update(
                scope=self.scope,
                rating_root=root_identity(self._root),
                revision=revision,
                built_at=_text(metrics.get("generated_at")),
                report_revision=measured_revision,
                report_stale=measured_revision != revision
                if _DIGEST.fullmatch(measured_revision)
                else loaded.path.stat().st_mtime_ns
                > self._report_paths(run_id)[1].stat().st_mtime_ns,
                report_status=_text(assessment.get("readiness"))
                if isinstance(assessment, dict)
                else "",
                pairs=self._verified_pairs(assessment, rows, media),
            )
        return result

    def _motion_review(
        self,
        job: dict[str, Any],
        case: dict[str, Any],
        cell: dict[str, Any],
        assessed: dict[str, Any],
        media: dict[str, _Asset],
    ) -> dict[str, Any] | None:
        case_motion, job_motion = case.get("motion"), job.get("motion")
        if not isinstance(case_motion, dict) or not isinstance(job_motion, dict):
            return None
        evidence = assessed.get("motion")
        context = ""
        drivers: dict[str, str | None] = {}
        if (
            isinstance(evidence, dict)
            and assessed.get("case_id") == job["case_id"]
            and assessed.get("arm_id") == job["arm_id"]
            and assessed.get(ARTIFACT_COLUMN) == cell.get(ARTIFACT_COLUMN)
            and evidence.get("integrity") == "verified_comparable"
            and _DIGEST.fullmatch(_text(evidence.get(CONTEXT_COLUMN)))
            and all(
                _DIGEST.fullmatch(_text(job_motion.get(f"driver_{kind}_sha256")))
                and evidence.get(f"driver_{kind}_sha256") == job_motion[f"driver_{kind}_sha256"]
                for kind in ("original", "effective")
            )
        ):
            context = evidence[CONTEXT_COLUMN]
            for kind in ("original", "effective"):
                path_value = job_motion.get(f"driver_{kind}_path")
                drivers[kind] = self._register(
                    path_value,
                    job_motion.get(f"driver_{kind}_sha256"),
                    "video/",
                    media,
                )
                if isinstance(path_value, str) and not drivers[kind]:
                    path = Path(path_value)
                    # Missing or linked media inside the grant invalidates the recorded context.
                    if not path.is_absolute() or path.is_relative_to(self._root):
                        context = ""
        return {
            CONTEXT_COLUMN: context,
            "driver_sha256": _text(job_motion.get("driver_effective_sha256")),
            "driver": drivers.get("effective"),
            "original_driver": drivers.get("original"),
            "action": _text(case_motion.get("action")),
            "expected_outcome": _text(case_motion.get("expected_outcome"), limit=8000),
        }

    @staticmethod
    def _verified_pairs(
        assessment: object, rows: list[dict[str, Any]], media: dict[str, _Asset]
    ) -> list[dict[str, str]]:
        if not isinstance(assessment, dict) or not isinstance(assessment.get("comparisons"), list):
            return []
        playable = {
            (row["case"], row["arm_id"])
            for row in rows
            if row["clip"]
            and row["source"]
            and media[row["clip"]].mime in {"video/mp4", "video/webm"}
        }
        pairs = []
        for item in assessment["comparisons"][:_MAX_CELLS]:
            if not isinstance(item, dict) or item.get("comparability") != "verified":
                continue
            case_id, baseline, candidate = (
                _text(item.get(key)) for key in ("case_id", "baseline_arm", "candidate_arm")
            )
            if (
                baseline != candidate
                and baseline == assessment.get("baseline_arm")
                and (case_id, baseline) in playable
                and (case_id, candidate) in playable
            ):
                pairs.append({"case": case_id, "baseline": baseline, "candidate": candidate})
        return pairs

    def _ratings(self, run_id: str) -> LoadedRatings:
        try:
            directory = self._report_paths(run_id)[0].parent
            path = self._inside(directory / "ratings.csv")
            return load_ratings(path, reader=self._read_ratings_file)
        except (OSError, RatingsFileError) as exc:
            raise SiteOutputError("ratings_unavailable") from exc

    def _read_ratings_file(self, path: Path) -> bytes:
        with open_scoped(self._root, path) as stream:
            return stream.read(MAX_RATINGS_BYTES + 1)

    def save_rating(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        fields = {
            *KEY_COLUMNS,
            "scope",
            "revision",
            "rebind",
            "judgments",
            ARTIFACT_COLUMN,
            "source_sha256",
        }
        durable = "sync" in body
        if durable:
            fields.add("sync")
        context = _text(body.get(CONTEXT_COLUMN))
        if CONTEXT_COLUMN in body:
            fields.add(CONTEXT_COLUMN)
        patch = body.get("judgments")
        if (
            set(body) != fields
            or not isinstance(patch, dict)
            or not patch
            or body.get("scope") != self.scope
            or type(body.get("rebind")) is not bool
            or any(
                not isinstance(body.get(name), str)
                for name in fields - {"rebind", "judgments", "sync"}
            )
            or any(
                key not in _ALL_JUDGMENTS or not isinstance(value, str) or len(value) > 8000
                for key, value in patch.items()
            )
            or parse_rating_row(patch).issues
        ):
            raise SiteOutputError("invalid_rating")
        sync = body.get("sync")
        stamp = None
        if durable:
            stamp = self._rating_stamp(run_id, body, sync)
        motion_edit = CONTEXT_COLUMN in body or bool(patch.keys() & _MOTION_JUDGMENTS)
        report_checks = (
            [(path, path.stat()) for path in self._report_paths(run_id)] if motion_edit else []
        )
        report = self.get_run(run_id, review=True)
        case_id, arm_id, job_id = (body[name] for name in KEY_COLUMNS)
        clip = next(
            (
                item
                for item in report["clips"]
                if (item["case"], item["arm_id"], item["job_id"]) == (case_id, arm_id, job_id)
            ),
            None,
        )
        if (
            clip is None
            or not clip["clip"]
            or not clip["source"]
            or clip[ARTIFACT_COLUMN] != body[ARTIFACT_COLUMN]
            or clip["source_sha256"] != body["source_sha256"]
        ):
            raise SiteOutputError("media_changed")
        motion = clip.get("motion")
        checks = [
            *report_checks,
            self.verify_media(clip["clip"]),
            self.verify_media(clip["source"]),
        ]
        if motion_edit:
            if not motion or not context or context != motion[CONTEXT_COLUMN]:
                raise SiteOutputError("motion_context_changed")
            # Only check drivers already within the approved output grant.
            checks.extend(
                self.verify_media(motion[key])
                for key in ("driver", "original_driver")
                if motion[key]
            )
        loaded = self._ratings(run_id)
        revision = hashlib.sha256(loaded.raw or b"").hexdigest()
        key = (case_id, arm_id, job_id)
        previous = loaded.keyed().get(key)
        if previous is None:
            raise SiteOutputError("ratings_conflict")
        digest = body[ARTIFACT_COLUMN]
        extra = {}
        if stamp is not None and isinstance(sync, dict):
            receipts = self._read_rating_receipts(previous)
            operation = sync["operation"]
            if was_applied(receipts, operation, stamp):
                return {"revision": revision, "saved": True}
            current = {name: previous.get(name, "") for name in patch}
            conflicts = field_conflicts(current, sync["base"], patch)
            bound = previous.get(ARTIFACT_COLUMN, "")
            if bound not in {sync["base_artifact_sha256"], digest}:
                conflicts[ARTIFACT_COLUMN] = bound
            if conflicts:
                return {"revision": revision, "conflict": conflicts}
            extra[_RECEIPTS_COLUMN] = json.dumps({**receipts, operation: stamp}, sort_keys=True)
        else:
            matches = (
                previous.get(ARTIFACT_COLUMN) == digest
                and (not motion_edit or previous.get(CONTEXT_COLUMN) == context)
                and all(previous.get(column, "") == value for column, value in patch.items())
            )
            if matches:
                return {"revision": revision, "saved": True}
            if revision != body["revision"]:
                raise SiteOutputError("ratings_conflict")
        if previous.get(ARTIFACT_COLUMN) != digest and row_has_content(previous):
            required = _ALL_JUDGMENTS if motion else _JUDGMENTS
            if not body["rebind"] or patch.keys() != required:
                raise SiteOutputError("rereview_required")
        if (
            motion_edit
            and previous.get(CONTEXT_COLUMN) != context
            and (previous.get(CONTEXT_COLUMN) or row_has_motion_content(previous))
            and (not body["rebind"] or not _MOTION_REVIEW_FIELDS <= patch.keys())
        ):
            raise SiteOutputError("rereview_required")
        if parse_rating_row(patch, duration_seconds=clip["duration"]).issues:
            raise SiteOutputError("invalid_rating")
        if motion_edit:
            extra.update({CONTEXT_COLUMN: context, RUBRIC_COLUMN: MOTION_RUBRIC_VERSION})
        updated = {**previous, **patch, **extra, ARTIFACT_COLUMN: digest}
        rows = [
            updated if tuple(row[name] for name in KEY_COLUMNS) == key else row
            for row in loaded.rows
        ]
        try:
            header = output_header(loaded, motion=motion_edit)
            if durable and _RECEIPTS_COLUMN not in header:
                header = (*header, _RECEIPTS_COLUMN)
            all_rows = (*rows, *loaded.keyless)
            expected = render_csv(header, all_rows).encode("utf-8")
            if len(expected) > MAX_RATINGS_BYTES:
                raise SiteOutputError("rating_store_full")
            write_ratings(
                loaded,
                header,
                all_rows,
                before_replace=lambda: self._confirm_rating_media(*checks),
                reader=self._read_ratings_file,
            )
        except RatingsFileError as exc:
            raise SiteOutputError("rating_retry" if durable else "ratings_conflict") from exc
        saved = self._ratings(run_id)
        if saved.raw != expected:
            raise SiteOutputError("rating_retry" if durable else "ratings_conflict")
        return {"revision": hashlib.sha256(saved.raw or b"").hexdigest(), "saved": True}

    def _rating_stamp(self, run_id: str, body: dict[str, Any], sync: Any) -> dict[str, str]:
        if (
            not isinstance(sync, dict)
            or set(sync) != {"root", "base", "base_artifact_sha256", "operation", "actor_time"}
            or not isinstance(sync["base"], dict)
            or sync["base"].keys() != body["judgments"].keys()
            or any(
                not isinstance(value, str) or len(value) > 8000 for value in sync["base"].values()
            )
            or not isinstance(sync["base_artifact_sha256"], str)
            or len(sync["base_artifact_sha256"]) > 64
            or not _DIGEST.fullmatch(body["revision"])
        ):
            raise SiteOutputError("invalid_rating")
        if sync["root"] != root_identity(self._root):
            raise SiteOutputError("output_folder_changed")
        return edit_stamp(
            sync["operation"],
            sync["actor_time"],
            (run_id, {key: value for key, value in body.items() if key != "scope"}),
        )

    @staticmethod
    def _read_rating_receipts(row: dict[str, str]) -> dict[str, Any]:
        try:
            receipts = json.loads(row.get(_RECEIPTS_COLUMN) or "{}")
        except (ValueError, RecursionError) as exc:
            raise SiteOutputError("ratings_unavailable") from exc
        if not isinstance(receipts, dict):
            raise SiteOutputError("ratings_unavailable")
        return receipts

    def _asset(self, identifier: str) -> _Asset:
        with self._lock:
            asset = self._media.get(identifier) or self._results.get(identifier)
        if asset is None:
            raise SiteOutputError("unknown_media")
        return asset

    def verify_media(self, identifier: str) -> tuple[Path, os.stat_result]:
        asset = self._asset(identifier)
        with open_scoped(self._root, asset.path) as stream:
            version = os.fstat(stream.fileno())
            if stream.seek(0, 2) > 512 * 1024 * 1024:
                raise SiteOutputError("media_too_large")
            stream.seek(0)
            if checked_digest(stream, size_limit=512 * 1024 * 1024) != asset.sha256:
                raise SiteOutputError("media_changed")
            return asset.path, version

    def _confirm_rating_media(self, *checks: tuple[Path, os.stat_result]) -> None:
        for path, version in checks:
            current = self._inside(path).stat()
            if (
                not os.path.samestat(version, current)
                or version.st_mtime_ns != current.st_mtime_ns
                or version.st_size != current.st_size
            ):
                raise SiteOutputError("media_changed")
        self.require_active()

    def open_video(self, identifier: str, *, library: bool) -> dict[str, object]:
        if not library:
            asset = self._asset(identifier)
            return self.playback.prepare(asset.path, asset.mime, asset.sha256)
        item = self.library.item(identifier)
        path = self.library.path_for(item)
        with self._lock:
            evidence = next(
                (
                    asset
                    for asset in reversed(tuple(self._media.values()))
                    if asset.path == path and asset.run_id
                ),
                None,
            )
        result = self.playback.prepare(path, item.mime, evidence.sha256 if evidence else None)
        self.library.path_for(item)
        if evidence:
            result["eval_run"] = evidence.run_id
        return result

    def read_media(self, identifier: str) -> tuple[str, bytes]:
        asset = self._asset(identifier)
        try:
            with open_scoped(self._root, asset.path) as stream:
                data = stream.read(_MAX_MEDIA + 1)
        except OSError as exc:
            raise SiteOutputError("media_unavailable") from exc
        if len(data) > _MAX_MEDIA:
            raise SiteOutputError("media_too_large")
        if hashlib.sha256(data).hexdigest() != asset.sha256:
            raise SiteOutputError("media_changed")
        return asset.mime, data

    def results(self, paths: list[str]) -> list[dict[str, str]]:
        results: dict[str, _Asset] = {}
        for item in paths[:12]:
            path = Path(item)
            if not path.is_absolute():
                path = (
                    self._root.parent if path.parts[0:1] == (self._root.name,) else self._root
                ) / path
            try:
                path = self._inside(path)
                mime = MEDIA_TYPES.get(path.suffix.lower())
                if mime is None or not path.is_file():
                    continue
                with open_scoped(self._root, path) as stream:
                    limit = VIDEO_LIMIT if mime in ("video/mp4", "video/webm") else _MAX_MEDIA
                    if not 0 < stream.seek(0, 2) <= limit:
                        continue
                    stream.seek(0)
                    digest = checked_digest(stream, size_limit=limit)
                results[secrets.token_hex(16)] = _Asset(path, digest, mime)
            except (OSError, SiteOutputError):
                continue
        with self._lock:
            self._results = results
        return [{"id": key, "type": asset.mime} for key, asset in results.items()]
