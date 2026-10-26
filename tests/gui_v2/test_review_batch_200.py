"""Synthetic real-Tk Review preparation and real SQLite admission; no runtime dispatch."""
from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import Mock

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.controller.app_controller import AppController
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.job_service import JobService
from src.controller.review_batch_service import prepare_review_batch
from src.gui.review_batch_dialog import ReviewBatchDialog
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1
from src.image_backends.operation_compatibility import OperationNotSupportedError
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.review.workflow_adapter import ReviewWorkflowAdapter
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    build_contract_kv,
    write_image_metadata,
)
from tests.controller.test_background_task_coordinator_v2 import _ThreadRegistryStub
from tests.helpers.njr_factory import make_pipeline_njr


@pytest.fixture
def workflow(tk_root, tmp_path, monkeypatch):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(JobQueue(repository=repository))
    assert not service.auto_run_enabled
    monkeypatch.setattr(service.runner, "start", lambda: pytest.fail("Runtime start prohibited"))
    controller = object.__new__(AppController)
    controller.job_service = service
    controller._append_log = lambda _: None
    controller._background_tasks = BackgroundTaskCoordinator(run_inline=True)
    controller._build_reprocess_config = lambda _: {
        "model": "sdxl-fallback.safetensors", "steps": 20, "cfg_scale": 7,
        "img2img": {"denoising_strength": 0.3},
    }
    tab = ReviewTabFrame(tk_root, app_controller=controller)
    monkeypatch.setattr("src.gui.review_batch_dialog.messagebox.showinfo", lambda *_, **__: None)
    yield controller, repository, tab
    for child in tab.winfo_children():
        if isinstance(child, ReviewBatchDialog):
            child.destroy()
    tab.destroy()


def images(tmp_path, count, *, incompatible=False):
    paths = []
    for index in range(count):
        path = tmp_path / f"source-{index:02}.png"
        Image.new("RGB", (32, 32), (index, 20, 40)).save(path)
        if index % 5 != 4 or incompatible and index == count - 1:
            model = ZIMAGE_PROFILE_V1.transformer.filename if incompatible and index == count - 1 else f"sdxl-{index % 3}.safetensors"
            payload = {"generation": {"model": model}, "stage_manifest": {
                "stage": "txt2img", "final_prompt": f"neutral source {index}",
                "config": {"steps": 20, "cfg_scale": 7},
            }}
            assert write_image_metadata(path, build_contract_kv(
                payload, job_id=f"parent-{index}", run_id="synthetic", stage="txt2img",
            ))
        paths.append(path)
    return paths


def prepare(controller, paths, **options):
    return prepare_review_batch(controller, image_paths=[str(path) for path in paths], stages=["img2img"],
        fallback_config=controller._build_reprocess_config(["img2img"]),
        prompt_delta="shared instruction", **options)


@pytest.mark.parametrize("count", [10, 25, 40])
def test_whole_selection_preview_maps_sources_and_admits_exact_jobs(workflow, tmp_path, count):
    controller, repository, tab = workflow
    paths = images(tmp_path, count)
    original = [path.read_bytes() for path in paths]
    tab._set_selected_images(paths)
    tab.stage_adetailer_var.set(False)
    tab.stage_img2img_var.set(True)
    tab.prompt_text.insert("1.0", "shared instruction")
    tab._reprocess(batch_all=True)
    dialog = next(child for child in tab.winfo_children() if isinstance(child, ReviewBatchDialog))
    preview = dialog.preview
    assert len(dialog.rows.get_children()) == count
    assert len(preview.jobs) == count and not preview.blocked
    assert not repository.list_jobs()
    for index, record in enumerate(preview.jobs):
        assert list(record.input_image_paths) == [str(paths[index])]
        assert record.images_per_prompt == 1
        assert record.extra_metadata["batch_id"] == preview.batch_id
        expected_prompt = "shared instruction" if index % 5 == 4 else f"neutral source {index}, shared instruction"
        assert record.positive_prompt == expected_prompt
        assert record.source.parent_job_id == (None if index % 5 == 4 else f"parent-{index}")
        assert record.source.parent_artifact_id == "sha256:" + hashlib.sha256(original[index]).hexdigest()
        frozen = NormalizedJobRecord.from_dict(record.to_dict())
        edited = frozen.extra_metadata
        edited["batch_id"] = "mutated"
        assert frozen.extra_metadata["batch_id"] == preview.batch_id
    dialog._confirm()
    dialog._confirm()  # even direct duplicate invocation cannot admit the batch twice
    assert len(repository.list_jobs(limit=100)) == count
    for job in preview.jobs:
        assert repository.get_job_model(job.job_id)._normalized_record.to_dict() == job.to_dict()
    assert [path.read_bytes() for path in paths] == original


@pytest.mark.parametrize("count", [10, 25, 40])
def test_incompatible_source_is_visible_excluded_only_explicitly_and_repreviewed(workflow, tmp_path, count):
    controller, repository, tab = workflow
    paths = images(tmp_path, count, incompatible=True)
    preview = prepare(controller, paths)
    assert len(preview.items) == count and len(preview.blocked) == 1
    assert preview.blocked[0].path == str(paths[-1])
    assert "stage(s) img2img are outside its qualified envelope" in preview.blocked[0].error
    with pytest.raises(OperationNotSupportedError, match="Nothing was queued"):
        controller.submit_review_reprocess_batch(preview)
    assert not repository.list_jobs()
    remaining = []
    dialog = ReviewBatchDialog(tab, preview, submit=controller.submit_review_reprocess_batch_async,
        repreview=remaining.append, visibility=tab._visibility_resolver())
    assert dialog.submit_button.instate(["disabled"])
    assert len(dialog.rows.get_children()) == count
    dialog._exclude()
    assert remaining == [[str(path) for path in paths[:-1]]]
    corrected = prepare(controller, [Path(path) for path in remaining[0]])
    assert len(corrected.jobs) == count - 1 and not corrected.blocked
    assert controller.submit_review_reprocess_batch(corrected) == count - 1


@pytest.mark.parametrize("count", [10, 25, 40])
def test_optional_stable_model_order_preserves_existing_queue_and_one_job_per_source(workflow, tmp_path, count):
    controller, repository, _ = workflow
    existing = make_pipeline_njr(job_id="existing", positive_prompt="existing queued work")
    controller.job_service.submit_njrs([existing])
    before = repository.get_job(existing.job_id)
    paths = images(tmp_path, count)
    original = prepare(controller, paths)
    grouped = prepare(controller, paths, group_by_model=True)
    assert [list(job.input_image_paths)[0] for job in original.jobs] == [str(path) for path in paths]
    assert [list(job.input_image_paths)[0] for job in grouped.jobs] == [
        list(job.input_image_paths)[0] for job in sorted(original.jobs, key=lambda job: job.base_model.casefold())
    ]
    assert len(grouped.jobs) == count and all(job.images_per_prompt == 1 for job in grouped.jobs)
    controller.submit_review_reprocess_batch(grouped)
    queue = controller.job_service.job_queue
    assert [job.job_id for job in queue.list_active_jobs_ordered()] == [existing.job_id, *[job.job_id for job in grouped.jobs]]
    assert repository.get_job(existing.job_id) == before


def test_missing_files_aggregate_all_errors_and_changed_source_requires_repreview(workflow, tmp_path):
    controller, repository, _ = workflow
    paths = images(tmp_path, 10)
    paths[2].unlink()
    paths[7].unlink()
    preview = prepare(controller, paths)
    assert {item.path for item in preview.blocked} == {str(paths[2]), str(paths[7])}
    with pytest.raises(ValueError, match="Nothing queued"):
        controller.submit_review_reprocess_batch(preview)
    assert not repository.list_jobs()
    valid = prepare(controller, [path for path in paths if path.exists()])
    paths[0].write_bytes(b"changed")
    with pytest.raises(ValueError, match="Source changed"):
        controller.submit_review_reprocess_batch(valid)
    assert not repository.list_jobs()


def test_cancel_preview_has_no_queue_history_or_source_side_effects(workflow, tmp_path):
    controller, repository, tab = workflow
    paths = images(tmp_path, 10)
    preview = prepare(controller, paths)
    dialog = ReviewBatchDialog(tab, preview, submit=controller.submit_review_reprocess_batch_async,
        repreview=lambda _: None, visibility=tab._visibility_resolver())
    dialog.destroy()
    assert not repository.list_jobs()
    assert all(path.exists() for path in paths)


def test_batch_jobs_reuse_repository_failure_and_service_cancellation(workflow, tmp_path):
    controller, repository, _ = workflow
    preview = prepare(controller, images(tmp_path, 10))
    assert controller.submit_review_reprocess_batch(preview) == 10
    failed, cancelled, unaffected = preview.jobs[:3]
    controller.job_service.job_queue.mark_running(failed.job_id)
    controller.job_service.job_queue.mark_failed(failed.job_id, "synthetic backend refusal")
    controller.job_service.cancel_job(cancelled.job_id, reason="operator cancelled")
    assert repository.get_job_model(failed.job_id).status == JobStatus.FAILED
    assert repository.get_job_model(cancelled.job_id).status == JobStatus.CANCELLED
    assert repository.get_job_model(unaffected.job_id).status == JobStatus.QUEUED
    for job in preview.jobs:
        assert repository.get_job_model(job.job_id)._normalized_record.to_dict() == job.to_dict()


def test_legacy_explicit_batch_size_keeps_compatible_multi_source_behavior(workflow, tmp_path):
    controller, _, _ = workflow
    paths = images(tmp_path, 10)
    controller._extract_reprocess_baseline_from_image = lambda _: {}
    preview = prepare(controller, paths, batch_size=3)
    assert [len(job.input_image_paths) for job in preview.jobs] == [3, 3, 3, 1]
    assert controller.submit_review_reprocess_batch(preview) == 4


def test_selection_preview_never_admits_and_config_capture_precedes_worker(workflow, tmp_path):
    controller, repository, _ = workflow
    paths = images(tmp_path, 10)
    submitted, callbacks, worker_ids = [], [], []
    main_id = get_ident()
    registry = _ThreadRegistryStub()
    controller._background_tasks = BackgroundTaskCoordinator(dispatcher=callbacks.append, thread_registry=registry)
    config = controller._build_reprocess_config
    def capture(stages):
        assert get_ident() == main_id
        return config(stages)
    controller._build_reprocess_config = capture
    baseline = controller._extract_reprocess_baseline_from_image
    def extract(path):
        worker_ids.append(get_ident())
        return baseline(path)
    controller._extract_reprocess_baseline_from_image = extract
    controller.preview_review_reprocess_batch(image_paths=[str(path) for path in paths], stages=["img2img"],
        on_preview=lambda plan: submitted.append((get_ident(), plan)), on_error=lambda exc: pytest.fail(str(exc)))
    for thread in registry.threads:
        thread.join(5)
        assert not thread.is_alive()
    assert not submitted and callbacks
    for callback in callbacks:
        callback()
    assert all(worker_id != main_id for worker_id in worker_ids)
    assert submitted[0][0] == main_id
    submitted = [pair[1] for pair in submitted]
    assert len(submitted) == 1 and len(submitted[0].jobs) == 10
    assert not repository.list_jobs()


def test_corrupt_image_is_blocked_but_malformed_metadata_has_explicit_fallback(workflow, tmp_path):
    controller, repository, _ = workflow
    paths = images(tmp_path, 10)
    paths[2].write_bytes(b"not an image")
    assert write_image_metadata(paths[3], {
        ImageMetadataContractV26.KEY_SCHEMA: ImageMetadataContractV26.SCHEMA,
        ImageMetadataContractV26.KEY_PAYLOAD: "not valid JSON",
    })
    preview = prepare(controller, paths)
    assert len(preview.items) == 10
    assert [item.path for item in preview.blocked] == [str(paths[2])]
    assert preview.items[3].metadata_source.startswith("fallback (metadata ")
    assert preview.items[3].prompt == "shared instruction"
    with pytest.raises(ValueError, match="Nothing queued"):
        controller.submit_review_reprocess_batch(preview)
    assert not repository.list_jobs()


def test_dialog_exposes_frozen_negative_stage_profile_output_and_lineage(workflow, tmp_path):
    controller, _, tab = workflow
    paths = images(tmp_path, 10)
    preview = prepare(controller, paths, negative_prompt_delta="avoid artifacts")
    dialog = ReviewBatchDialog(tab, preview, submit=controller.submit_review_reprocess_batch_async,
        repreview=lambda _: None, visibility=tab._visibility_resolver())
    detail = dialog.details.get("1.0", "end")
    assert "Negative prompt: avoid artifacts" in detail
    assert "img2img: sampler=Euler a" in detail and "steps=20, CFG=7.0, denoise=0.3" in detail
    assert "Backend/profile:" in detail and "Output directory:" in detail
    assert "Parent job: parent-0" in detail and "Source artifact: sha256:" in detail
    assert preview.jobs[0].job_id in detail


def test_source_change_repreview_is_available_without_automatic_readmission(workflow, tmp_path, monkeypatch):
    controller, repository, tab = workflow
    paths = images(tmp_path, 10)
    preview = prepare(controller, paths)
    errors, requests = [], []
    monkeypatch.setattr("src.gui.review_batch_dialog.messagebox.showerror", lambda *args, **_: errors.append(args))
    dialog = ReviewBatchDialog(tab, preview, submit=controller.submit_review_reprocess_batch_async,
        repreview=requests.append, visibility=tab._visibility_resolver())
    paths[0].write_bytes(b"changed")
    dialog._confirm()
    assert errors and "Source changed" in errors[0][1]
    assert not repository.list_jobs()
    assert dialog.submit_button.instate(["disabled"])
    dialog._preview_all()
    assert requests == [[str(path) for path in paths]]


def _comment_image(path, value):
    info = PngInfo()
    info.add_text("comment", value)
    Image.new("RGB", (32, 32), (20, 30, 40)).save(path, pnginfo=info)


def _change_content_preserving_stat(path):
    original = path.stat()
    _comment_image(path, "after!")
    assert path.stat().st_size == original.st_size
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert path.stat().st_mtime_ns == original.st_mtime_ns
    with Image.open(path) as image:
        image.load()  # the replacement remains a valid PNG, not just corrupt bytes


def test_same_size_same_mtime_content_change_cannot_cross_admission(workflow, tmp_path):
    controller, repository, _ = workflow
    existing = make_pipeline_njr(job_id="existing")
    controller.job_service.submit_njrs([existing])
    path = tmp_path / "mutable.png"
    _comment_image(path, "before")
    preview = prepare(controller, [path])
    frozen = preview.jobs[0].to_dict()
    assert preview.jobs[0].source.parent_artifact_id == "sha256:" + preview.items[0].source_sha256
    _change_content_preserving_stat(path)
    with pytest.raises(ValueError, match="Source content changed; preview again"):
        controller.submit_review_reprocess_batch(preview)
    assert [row.job_id for row in repository.list_jobs()] == [existing.job_id]
    assert preview.jobs[0].to_dict() == frozen


def test_same_stat_content_change_during_preparation_is_blocked(workflow, tmp_path):
    controller, repository, _ = workflow
    path = tmp_path / "mutable.png"
    _comment_image(path, "before")
    def extract(_):
        _change_content_preserving_stat(path)
        return {}
    controller._extract_reprocess_baseline_from_image = extract
    preview = prepare(controller, [path])
    assert not preview.jobs
    assert "Source changed while preparing" in preview.blocked[0].error
    assert not repository.list_jobs()


@pytest.mark.parametrize("model,ready", [
    (ZIMAGE_PROFILE_V1.transformer.filename, False),
    ("flux-2-klein-4b-fp8.safetensors", False),
    ("ordinary.safetensors", True),
])
def test_whole_selection_agrees_with_img158_selected_readiness(workflow, tmp_path, model, ready):
    controller, repository, _ = workflow
    path = tmp_path / "source.png"
    _comment_image(path, "before")
    controller._extract_reprocess_baseline_from_image = lambda _: {"model": model, "prompt": "neutral", "config": {}}
    fallback = controller._build_reprocess_config(["img2img"])
    fallback["backend_options"] = {"image": {"backend_id": "forge_webui"}}
    controller._build_reprocess_config = lambda _: fallback
    selected = controller.get_review_reprocess_effective_settings_preview(image_path=str(path), stages=["img2img"])
    expected = ReviewWorkflowAdapter.assess_readiness(selected, backend_id="forge_webui")
    batch = prepare(controller, [path])
    assert expected.ready is ready
    assert (not batch.blocked) is ready
    if not ready:
        assert batch.blocked[0].assessment == expected
        with pytest.raises(OperationNotSupportedError) as refused:
            controller.submit_review_reprocess_batch(batch)
        assert refused.value.assessment == expected
    assert not repository.list_jobs()


def test_whole_selection_explicit_edit_matches_img158_and_final_preflight(workflow, tmp_path, monkeypatch):
    import src.controller.reprocess_admission as admission
    controller, repository, _ = workflow
    path = tmp_path / "source.png"
    Image.new("RGB", (1024, 1024)).save(path)
    marked = ReviewWorkflowAdapter.with_klein_edit_request(None, [path])
    controller._extract_reprocess_baseline_from_image = lambda _: {"model": ZIMAGE_PROFILE_V1.transformer.filename, "config": {}}
    preview = prepare(controller, [path], source_metadata_by_image=marked)
    assert not preview.blocked and preview.jobs[0].base_model == "flux-2-klein-4b-fp8.safetensors"
    verify = Mock(wraps=admission.require_njr_operation)
    monkeypatch.setattr(admission, "require_njr_operation", verify)
    assert controller.submit_review_reprocess_batch(preview) == 1
    verify.assert_called_once_with(preview.jobs[0])
    assert repository.get_job_model(preview.jobs[0].job_id)._normalized_record.to_dict() == preview.jobs[0].to_dict()


def test_even_a_forged_ready_preview_cannot_bypass_img158_final_admission(workflow, tmp_path):
    controller, repository, _ = workflow
    paths = images(tmp_path, 1)
    preview = prepare(controller, paths)
    unsupported = ReprocessJobBuilder().build_reprocess_job(
        input_image_paths=[str(paths[0])], stages=["img2img"],
        model=ZIMAGE_PROFILE_V1.transformer.filename,
        config={"backend_options": {"image": {"backend_id": "forge_webui"}}},
    )
    forged = replace(preview, jobs=(unsupported,))
    assert not forged.blocked
    with pytest.raises(OperationNotSupportedError):
        controller.submit_review_reprocess_batch(forged)
    assert not repository.list_jobs()


def test_admission_hashes_run_off_tk_and_dialog_confirms_only_once(workflow, tmp_path, monkeypatch):
    import src.controller.review_batch_service as batches
    controller, repository, tab = workflow
    preview = prepare(controller, images(tmp_path, 10))
    callbacks, hash_threads, results = [], [], []
    main_id, registry = get_ident(), _ThreadRegistryStub()
    controller._background_tasks = BackgroundTaskCoordinator(dispatcher=callbacks.append, thread_registry=registry)
    original_hash = batches._source_sha256
    def hash_source(path):
        hash_threads.append(get_ident())
        return original_hash(path)
    monkeypatch.setattr(batches, "_source_sha256", hash_source)
    monkeypatch.setattr("src.gui.review_batch_dialog.messagebox.showinfo", lambda *_, **__: results.append(get_ident()))
    dialog = ReviewBatchDialog(tab, preview, submit=controller.submit_review_reprocess_batch_async,
        repreview=lambda _: pytest.fail("Cannot re-preview while admission is pending"), visibility=tab._visibility_resolver())
    dialog._confirm()
    dialog._confirm()
    dialog._preview_all()
    assert dialog.cancel_button.instate(["disabled"]) and dialog.repreview_button.instate(["disabled"])
    for thread in registry.threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert hash_threads and all(thread != main_id for thread in hash_threads)
    assert len(repository.list_jobs()) == 10 and not results
    for callback in callbacks:
        callback()
    assert results == [main_id] and not dialog.winfo_exists()


def test_independent_confirmed_batches_do_not_drop_each_others_callbacks(workflow, tmp_path, monkeypatch):
    import src.controller.review_batch_service as batches
    controller, repository, _ = workflow
    paths = images(tmp_path, 2)
    first, second = prepare(controller, paths[:1]), prepare(controller, paths[1:])
    entered, release = Event(), Event()
    callbacks, results, errors = [], [], []
    registry = _ThreadRegistryStub()
    controller._background_tasks = BackgroundTaskCoordinator(dispatcher=callbacks.append, thread_registry=registry)
    original_hash = batches._source_sha256
    def hash_source(path):
        if path == paths[0]:
            entered.set()
            assert release.wait(timeout=5)
        return original_hash(path)
    monkeypatch.setattr(batches, "_source_sha256", hash_source)
    controller.submit_review_reprocess_batch_async(first, on_submitted=results.append, on_error=errors.append)
    assert entered.wait(timeout=5)
    controller.submit_review_reprocess_batch_async(second, on_submitted=results.append, on_error=errors.append)
    release.set()
    for thread in registry.threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    for callback in callbacks:
        callback()
    assert not errors and results == [1, 1]
    assert len(repository.list_jobs()) == 2
    assert controller._background_tasks.get_metrics_snapshot()["stale_dropped"] == 0
