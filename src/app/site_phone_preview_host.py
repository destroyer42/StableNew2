"""Capture native inputs on the GUI thread and run the existing Preview compilers off it."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.app.site_media_files import SiteOutputError
from src.app.site_native_review import NativeImageReview
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_pack_catalog import PreparePack, SitePackCatalog, pack_digest
from src.app.site_phone_admission import PhonePreviewInput
from src.contracts import PreviewRequest
from src.controller.app_controller_services.pack_draft_service import (
    build_pack_config,
    build_pack_entries,
)
from src.controller.review_batch_service import AdetailerPasses, prepare_review_batch
from src.pipeline.job_models_v2 import SourceKind
from src.pipeline.policy_warnings import with_pending_warnings
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.review.correction_advice import (
    ReviewResources,
    detectors_for,
    resolve_target,
    target_verdict,
)
from src.review.findings import Action
from src.review.review_lineage import LineageSource, find_review_children
from src.utils.file_io import read_prompt_pack


class PhonePreviewHost:
    def __init__(self, app: Any, repository: JobRepository, review_records: Path) -> None:
        self._app = app
        self._repository = repository
        self._review_records = review_records

    def _capture[T](self, read: Callable[[], T]) -> T:
        future: Future[T] = Future()

        def capture() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                if self._app._is_shutting_down:
                    raise SiteOutputError("app_shutting_down")
                future.set_result(read())
            except Exception as exc:  # noqa: BLE001 - transfer native callback failures to the request thread
                future.set_exception(exc)

        self._app._ui_dispatch(capture)
        try:
            return future.result(timeout=8)
        except TimeoutError as exc:
            future.cancel()
            raise SiteOutputError("preview_unavailable") from exc

    def packs(self) -> SitePackCatalog:
        app = self._app
        root, packs = self._capture(lambda: (app._packs_dir, list(app.packs)))
        return SitePackCatalog(root, packs)

    def compile_pack(self, command: PreparePack) -> PhonePreviewInput:
        app = self._app
        pack = command.pack

        def capture() -> tuple[Any, ...]:
            revision, _preview = app.app_state.snapshot_accepted_preview()
            return (
                revision,
                app._capture_pack_draft_config(),
                app._build_stage_flags(),
                deepcopy(app._build_randomizer_metadata()),
                app.pipeline_controller,
            )

        revision, draft_config, stages, randomizer, compiler = self._capture(capture)
        saved_config = deepcopy(app._config_manager.load_pack_config(pack.name) or {})

        def require_current() -> None:
            if (
                app._is_shutting_down
                or app.app_state.snapshot_accepted_preview()[0] != revision
                or not any(
                    item.name == pack.name and item.path.resolve() == pack.path
                    for item in app.packs
                )
                or pack_digest(pack.path) != command.digest
                or (app._config_manager.load_pack_config(pack.name) or {}) != saved_config
            ):
                raise SiteOutputError("preview_changed")

        prompts = read_prompt_pack(pack.path)
        if not stages.get("txt2img", True) or max(command.slots) >= len(prompts):
            raise SiteOutputError("image_preview_required")
        config_snapshot = build_pack_config(
            draft_config, deepcopy(saved_config), stages, randomizer
        )
        entries = build_pack_entries(
            pack.name,
            pack,
            prompts,
            config_snapshot,
            stages,
            randomizer,
            slots=command.slots,
        )
        require_current()
        jobs = tuple(
            compiler.get_preview_jobs_for_request(
                PreviewRequest(tuple(entries), use_state_fallback=False)
            )
        )
        if {job.prompt_pack_row_index for job in jobs} != set(command.slots) or any(
            job.source.kind is not SourceKind.PROMPT_PACK
            or job.input_image_paths
            or "txt2img" not in job.stage_chain_labels
            or job.prompt_pack_id != pack.name
            for job in jobs
        ):
            raise SiteOutputError("image_preview_required")
        return PhonePreviewInput(pack.name, jobs, require_current)

    def compile_rework(
        self, catalog: SiteOutputCatalog, key: str, digest: str, stage: str
    ) -> PhonePreviewInput:
        app = self._app
        review = NativeImageReview(catalog.library, self._review_records)
        path, mark, decided = review.rework_mark(key, digest)
        fallback, revision = self._capture(
            lambda: (
                deepcopy(app._build_reprocess_config([stage])),
                app.app_state.snapshot_accepted_preview()[0],
            )
        )
        preview = prepare_review_batch(
            app, image_paths=[str(path)], stages=[stage], fallback_config=fallback
        )
        if preview.blocked or len(preview.jobs) != 1:
            blocked = preview.blocked[0].assessment if preview.blocked else None
            if blocked is not None:
                raise SiteOutputError("rework_operation_unavailable")
            raise SiteOutputError("rework_preview_failed")
        if preview.jobs[0].source.parent_artifact_id != f"sha256:{digest}":
            raise SiteOutputError("media_changed")

        def require_current() -> None:
            current_path, current_mark, _stamp = review.rework_mark(key, digest)
            if (current_path, current_mark) != (
                path,
                mark,
            ) or app.app_state.snapshot_accepted_preview()[0] != revision:
                raise SiteOutputError("preview_changed")
            lineage = find_review_children(
                self._repository, (LineageSource(digest, digest),), limit=12
            )
            if any(
                child.active or (child.created_at > decided and child.status is JobStatus.COMPLETED)
                for child in lineage.children_of(digest)
            ):
                raise SiteOutputError("rework_already_in_progress_or_returned")
            preview.require_queueable()

        return PhonePreviewInput(path.name, preview.jobs, require_current)

    def compile_gateway_fix(
        self, path: Path, digest: str, *, face: bool, hands: bool
    ) -> PhonePreviewInput:
        """RG-140: the executor's ADetailer face and/or hand pass on exactly the image at ``path``.

        The current ADetailer settings and the backend's detector list are read on the Tk thread; the job is the
        existing Review re-work compile, so it writes under ``<output>/Reprocess`` and records its parent artifact.
        Refusals are closed codes (``SiteOutputError``), never compiler text.
        """

        app = self._app
        fallback, detectors = self._capture(
            lambda: (
                deepcopy(app._build_reprocess_config(["adetailer"])),
                tuple(getattr(app.app_state, "adetailer_detectors", None) or ()),
            )
        )
        baseline = app._extract_reprocess_baseline_from_image(path)
        target = resolve_target(baseline, fallback, "adetailer")
        action = Action.FACE if face else Action.HANDS
        verdict = target_verdict(action, target)
        if not verdict.allowed:  # N1b: only a positively identified other family is a real block
            raise SiteOutputError("model_family_refused")
        usable = [name for name in detectors if isinstance(name, str) and name.strip()]
        if not usable:
            raise SiteOutputError("adetailer_unavailable")
        resources = ReviewResources(frozenset(), tuple(usable), target.backend, True)
        faces = detectors_for(Action.FACE, resources) if face else ()
        hand_models = detectors_for(Action.HANDS, resources) if hands else ()
        if (face and not faces) or (hands and not hand_models):
            raise SiteOutputError("detector_unavailable")
        preview = prepare_review_batch(
            app,
            image_paths=[str(path)],
            stages=["adetailer"],
            fallback_config=fallback,
            adetailer_passes=AdetailerPasses(faces, hand_models),
        )
        if preview.blocked or len(preview.jobs) != 1:
            blocked = preview.blocked[0] if preview.blocked else None
            if blocked is not None and blocked.assessment is not None:
                raise SiteOutputError("operation_unsupported")
            raise SiteOutputError("compile_failed")
        job = preview.jobs[0]
        if job.source.parent_artifact_id != f"sha256:{digest}":
            raise SiteOutputError("source_changed")
        job = with_pending_warnings(job, verdict.warnings)
        return PhonePreviewInput(path.name, (job,), preview.require_queueable)
