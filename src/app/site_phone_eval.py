"""Scoped access to the desktop's native video evaluation report builder."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from threading import Event, Lock
from typing import Any

from src.app.site_media_files import SiteOutputError, inside, open_scoped
from src.app.site_output_catalog import SiteOutputCatalog
from src.queue.job_repository import JobRepository
from src.utils.thread_registry import get_thread_registry
from src.video.video_eval_ratings_store import MAX_RATINGS_BYTES
from src.video.video_eval_report import (
    METRICS_FILE,
    RATINGS_FILE,
    REPORT_FILE,
    EvalReportScope,
    build_eval_report,
)
from src.video.video_eval_suite import MAX_EVAL_JOBS

PHONE_EVAL_RUNS = "/v1/phone-eval/runs"
PHONE_EVAL_REFRESH = re.compile(r"/v1/phone-eval/refresh/(\d{8}_\d{6}_[A-Za-z0-9_-]{1,150})")
_REPORT_SECONDS = 300
log = logging.getLogger(__name__)


class _ReportCancellation(Event):
    def __init__(self, catalog: SiteOutputCatalog) -> None:
        super().__init__()
        self._catalog = catalog
        self._expires = time.monotonic() + _REPORT_SECONDS

    def require_active(self) -> None:
        self._catalog.require_active()
        if time.monotonic() >= self._expires:
            raise SiteOutputError("eval_report_timed_out")

    def is_set(self) -> bool:
        try:
            self.require_active()
        except SiteOutputError:
            return True
        return super().is_set()


class PhoneEvalReports:
    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository
        self._lock = Lock()
        self._latest: tuple[str, str, str] | None = None

    def list(self, catalog: SiteOutputCatalog) -> dict[str, Any]:
        with self._lock:
            latest = self._latest
        built = set(catalog.list_runs())
        return {
            "scope": catalog.scope,
            "runs": [
                {
                    "id": run_id,
                    "built": run_id in built,
                    "refresh": latest[2]
                    if latest and latest[:2] == (catalog.scope, run_id)
                    else None,
                }
                for run_id in catalog.list_runs(include_unbuilt=True)
            ],
        }

    def refresh(self, catalog: SiteOutputCatalog, run_id: str, body: object) -> dict[str, str]:
        if body != {"scope": catalog.scope}:
            raise SiteOutputError("invalid_report_refresh")
        with self._lock:
            if self._latest and self._latest[2] == "building":
                if self._latest[:2] == (catalog.scope, run_id):
                    return {"state": "building"}
                raise SiteOutputError("eval_report_busy")
            self._latest = catalog.scope, run_id, "building"

        def rebuild() -> None:
            state = "failed"
            try:
                self._build(catalog, run_id)
                state = "ready"
            except Exception:  # noqa: BLE001 - keep diagnostics on Windows and release the refresh slot
                log.exception("Unable to refresh the scoped eval report")
            finally:
                with self._lock:
                    self._latest = catalog.scope, run_id, state

        try:
            get_thread_registry().spawn(
                target=rebuild, name="StableNew eval report refresh", purpose="Scoped eval report"
            )
        except RuntimeError as exc:
            with self._lock:
                self._latest = catalog.scope, run_id, "failed"
            raise SiteOutputError("eval_report_unavailable") from exc
        return {"state": "building"}

    def _build(self, catalog: SiteOutputCatalog, run_id: str) -> None:
        cancel = _ReportCancellation(catalog)
        cancel.require_active()
        directory, manifest = catalog.eval_manifest(run_id)
        for field in ("cases", "arms", "jobs"):
            items = manifest.get(field)
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= MAX_EVAL_JOBS
                or any(not isinstance(item, dict) for item in items)
            ):
                raise SiteOutputError("invalid_report")
        root = catalog.library.root

        def permits_media(raw: str) -> bool:
            if not raw:
                return False
            try:
                return inside(root, Path(raw).absolute()).is_file()
            except FileNotFoundError:
                return False
            except SiteOutputError as exc:
                # A scoped rebuild cannot replace Windows evidence with a
                # projection that omitted an existing out-of-scope asset.
                raise RuntimeError("A report asset is outside shared Output") from exc

        def read_ratings(path: Path) -> bytes | None:
            try:
                with open_scoped(root, path) as handle:
                    return handle.read(MAX_RATINGS_BYTES + 1)
            except FileNotFoundError:
                return None

        def require_publishable() -> None:
            cancel.require_active()
            current_dir, current_manifest = catalog.eval_manifest(run_id)
            if current_dir != directory or current_manifest != manifest:
                raise SiteOutputError("eval_report_changed")
            for name in (RATINGS_FILE, METRICS_FILE, REPORT_FILE):
                try:
                    if not inside(root, directory / name).is_file():
                        raise SiteOutputError("invalid_report")
                except FileNotFoundError:
                    continue

        require_publishable()
        build_eval_report(
            directory,
            self._repository,
            cancel=cancel,
            show_prompts=False,
            scope=EvalReportScope(
                manifest, permits_media, read_ratings, cancel.require_active, require_publishable
            ),
        )
