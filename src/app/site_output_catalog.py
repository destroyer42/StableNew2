"""Read-only projection of eval reports and exact media from an operator-approved output root."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any

from src.app.site_media_files import MEDIA_TYPES, checked_digest, inside, open_scoped
from src.app.site_media_files import SiteOutputError as SiteOutputError
from src.app.site_output_library import OutputLibrary
from src.app.site_video_playback import VideoPlayback
from src.video.video_eval_ratings_store import (
    ARTIFACT_COLUMN,
    KEY_COLUMNS,
    MAX_RATINGS_BYTES,
    RATING_COLUMNS,
    LoadedRatings,
    RatingsFileError,
    load_ratings,
    output_header,
    render_csv,
    write_ratings,
)
from src.video.video_eval_rubric import parse_rating_row, row_has_content
from src.video.video_eval_run import EVAL_OUTPUT_FOLDER, RUN_MANIFEST_NAME, RUN_SCHEMA

_REPORT_SCHEMA = "stablenew.video-eval-report.v1"
_RUN_ID = re.compile(r"\d{8}_\d{6}_[a-zA-Z0-9_-]{1,150}")
_DIGEST = re.compile(r"[a-f0-9]{64}")
_MAX_REPORT = 5 * 1024 * 1024
_MAX_MEDIA = 64 * 1024 * 1024
_MAX_RUNS = 100
_MAX_CELLS = 500
_JUDGMENTS = set(RATING_COLUMNS) - {*KEY_COLUMNS, ARTIFACT_COLUMN}


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

    def __init__(self, output_root: Path, *, active: Callable[[], bool] = lambda: True) -> None:
        self._root = output_root.resolve(strict=True)
        if not self._root.is_dir():
            raise SiteOutputError("output_folder_required")
        self._lock = Lock()
        self._revoked = Event()
        self._active = active
        self.scope = secrets.token_hex(16)
        self.library = OutputLibrary(self._root, self.scope, self.require_active)
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

    def _inside(self, path: Path) -> Path:
        return inside(self._root, path)

    def _report_paths(self, run_id: str) -> tuple[Path, Path]:
        if not _RUN_ID.fullmatch(run_id):
            raise SiteOutputError("unknown_run")
        directory = self._inside(self._root / EVAL_OUTPUT_FOLDER / run_id)
        return (
            self._inside(directory / RUN_MANIFEST_NAME),
            self._inside(directory / "metrics.json"),
        )

    def list_runs(self) -> list[str]:
        try:
            root = self._inside(self._root / EVAL_OUTPUT_FOLDER)
            candidates = sorted(
                (path.name for path in root.iterdir() if _RUN_ID.fullmatch(path.name)),
                reverse=True,
            )
        except (OSError, SiteOutputError):
            return []
        runs = []
        for name in candidates:
            try:
                manifest, metrics = self._report_paths(name)
                if manifest.is_file() and metrics.is_file():
                    runs.append(name)
            except (OSError, SiteOutputError):
                continue
            if len(runs) == _MAX_RUNS:
                break
        return runs

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
                cell_metrics = cell.get("metrics")
                duration = (
                    cell_metrics.get("duration_seconds") if isinstance(cell_metrics, dict) else None
                )
                row.update(
                    arm_id=arm_id,
                    prompt=_text(case.get("prompt"), limit=8000),
                    source_sha256=_text(source_hash).lower(),
                    artifact_sha256=_text(cell.get("artifact_sha256")).lower(),
                    duration=duration if isinstance(duration, (float, int)) else None,
                    rating={
                        key: value
                        for key, value in saved.items()
                        if key in _JUDGMENTS or key == ARTIFACT_COLUMN
                    },
                )
            rows.append(row)
        with self._lock:
            self._media.update(media)
            if len(self._media) > 4000:
                self._media = dict(list(self._media.items())[-3000:])
        result: dict[str, Any] = {"run_id": run_id, "clips": rows}
        if loaded is not None:
            result.update(
                scope=self.scope,
                revision=hashlib.sha256(loaded.raw or b"").hexdigest(),
                built_at=_text(metrics.get("generated_at")),
                report_stale=loaded.path.stat().st_mtime_ns
                > self._report_paths(run_id)[1].stat().st_mtime_ns,
                report_status=_text(assessment.get("readiness"))
                if isinstance(assessment, dict)
                else "",
            )
        return result

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
        patch = body.get("judgments")
        if (
            set(body) != fields
            or not isinstance(patch, dict)
            or not patch
            or body.get("scope") != self.scope
            or type(body.get("rebind")) is not bool
            or any(not isinstance(body.get(name), str) for name in fields - {"rebind", "judgments"})
            or any(
                key not in _JUDGMENTS or not isinstance(value, str) or len(value) > 8000
                for key, value in patch.items()
            )
            or parse_rating_row(patch).issues
        ):
            raise SiteOutputError("invalid_rating")
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
        self.verify_media(clip["clip"])
        self.verify_media(clip["source"])
        loaded = self._ratings(run_id)
        revision = hashlib.sha256(loaded.raw or b"").hexdigest()
        key = (case_id, arm_id, job_id)
        previous = loaded.keyed().get(key)
        if previous is None:
            raise SiteOutputError("ratings_conflict")
        digest = body[ARTIFACT_COLUMN]
        matches = previous.get(ARTIFACT_COLUMN) == digest and all(
            previous.get(column, "") == value for column, value in patch.items()
        )
        if matches:
            return {"revision": revision, "saved": True}
        if revision != body["revision"]:
            raise SiteOutputError("ratings_conflict")
        if previous.get(ARTIFACT_COLUMN) != digest and row_has_content(previous):
            if not body["rebind"] or set(patch) != _JUDGMENTS:
                raise SiteOutputError("rereview_required")
        if parse_rating_row(patch, duration_seconds=clip["duration"]).issues:
            raise SiteOutputError("invalid_rating")
        updated = {**previous, **patch, ARTIFACT_COLUMN: digest}
        rows = [
            updated if tuple(row[name] for name in KEY_COLUMNS) == key else row
            for row in loaded.rows
        ]
        try:
            header = output_header(loaded)
            all_rows = (*rows, *loaded.keyless)
            expected = render_csv(header, all_rows).encode("utf-8")
            write_ratings(
                loaded,
                header,
                all_rows,
                before_replace=self.require_active,
                reader=self._read_ratings_file,
            )
        except RatingsFileError as exc:
            raise SiteOutputError("ratings_conflict") from exc
        saved = self._ratings(run_id)
        if saved.raw != expected:
            raise SiteOutputError("ratings_conflict")
        return {"revision": hashlib.sha256(saved.raw or b"").hexdigest(), "saved": True}

    def _asset(self, identifier: str) -> _Asset:
        with self._lock:
            asset = self._media.get(identifier) or self._results.get(identifier)
        if asset is None:
            raise SiteOutputError("unknown_media")
        return asset

    def verify_media(self, identifier: str) -> None:
        asset = self._asset(identifier)
        with open_scoped(self._root, asset.path) as stream:
            if stream.seek(0, 2) > 512 * 1024 * 1024:
                raise SiteOutputError("media_too_large")
            stream.seek(0)
            if checked_digest(stream, size_limit=512 * 1024 * 1024) != asset.sha256:
                raise SiteOutputError("media_changed")

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
                    raw = stream.read(_MAX_MEDIA + 1)
                if len(raw) <= _MAX_MEDIA:
                    results[secrets.token_hex(16)] = _Asset(
                        path, hashlib.sha256(raw).hexdigest(), mime
                    )
            except (OSError, SiteOutputError):
                continue
        with self._lock:
            self._results = results
        return [{"id": key, "type": asset.mime} for key, asset in results.items()]
