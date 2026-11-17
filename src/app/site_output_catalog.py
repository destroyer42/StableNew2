"""Read-only projection of eval reports and exact media from an operator-approved output root."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from src.video.video_eval_run import EVAL_OUTPUT_FOLDER, RUN_MANIFEST_NAME, RUN_SCHEMA

_REPORT_SCHEMA = "stablenew.video-eval-report.v1"
_RUN_ID = re.compile(r"\d{8}_\d{6}_[a-zA-Z0-9_-]{1,150}")
_DIGEST = re.compile(r"[a-f0-9]{64}")
_MAX_REPORT = 5 * 1024 * 1024
_MAX_MEDIA = 64 * 1024 * 1024
_MAX_RUNS = 100
_MAX_CELLS = 500
_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".m4v": "video/mp4",
}


class SiteOutputError(ValueError):
    """A bounded, path-free refusal suitable for display in the Site."""


@dataclass(frozen=True)
class _Asset:
    path: Path
    sha256: str
    mime: str


def _bounded_json(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
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

    def __init__(self, output_root: Path) -> None:
        self._root = output_root.resolve(strict=True)
        if not self._root.is_dir():
            raise SiteOutputError("output_folder_required")
        self._lock = Lock()
        self._media: dict[str, _Asset] = {}
        self._results: dict[str, _Asset] = {}

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self._root):
            raise SiteOutputError("outside_output_folder")
        return resolved

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
            mime = _MIME.get(resolved.suffix.lower(), "")
            if not mime.startswith(prefix) or not resolved.is_file():
                return None
        except (OSError, SiteOutputError):
            return None
        identifier = secrets.token_hex(16)
        media[identifier] = _Asset(resolved, digest.lower(), mime)
        return identifier

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            manifest, metrics = map(_bounded_json, self._report_paths(run_id))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SiteOutputError("report_unavailable") from exc
        if (
            manifest.get("schema") != RUN_SCHEMA
            or metrics.get("schema") != _REPORT_SCHEMA
            or manifest.get("run_id") != run_id
            or metrics.get("run_id") != run_id
        ):
            raise SiteOutputError("invalid_report")

        cases = _index(manifest.get("cases"), "case_id")
        arms = _index(manifest.get("arms"), "arm_id")
        jobs = _index(manifest.get("jobs"), "job_id")
        cells = _index(metrics.get("cells"), "job_id")
        if not jobs or jobs.keys() != cells.keys():
            raise SiteOutputError("invalid_report")
        media: dict[str, _Asset] = {}
        rows = []
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
            rows.append(
                {
                    "case": case_id,
                    "arm": _text(arms[arm_id].get("label")) or arm_id,
                    "job_id": identity,
                    "state": state,
                    "review": _text(cell.get("assessment_state"), limit=40),
                    "clip": self._register(
                        cell.get("path"), cell.get("artifact_sha256"), "video/", media
                    )
                    if state == "playable"
                    else None,
                    "source": self._register(
                        case.get("image"), case.get("image_sha256"), "image/", media
                    ),
                }
            )
        with self._lock:
            self._media = media
        return {"run_id": run_id, "clips": rows}

    def read_media(self, identifier: str) -> tuple[str, bytes]:
        with self._lock:
            asset = self._media.get(identifier) or self._results.get(identifier)
        if asset is None:
            raise SiteOutputError("unknown_media")
        try:
            path = self._inside(asset.path)
            with path.open("rb") as stream:
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
                mime = _MIME.get(path.suffix.lower())
                if mime is None or not path.is_file():
                    continue
                with path.open("rb") as stream:
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
