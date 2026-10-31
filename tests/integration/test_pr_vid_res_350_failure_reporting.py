"""Actual Comfy backend with fake transport: allocation failures persist on the canonical queue."""

from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.queue.job_model import JobStatus
from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
from tests.pipeline.test_pr_vid_seq_330_runner import _intent
from tests.video.test_pr_vid_ux_311_preflight import _probes
from tests.video.test_wan22_experimental_workflow import _backend, _FakeComfy


@pytest.mark.parametrize(
    "exception_type, message",
    [("torch.OutOfMemoryError", "CUDA out of memory"), ("MemoryError", "host allocation failed")],
)
def test_backend_allocation_failure_is_persisted_without_duplicate_dispatch(
    tmp_path, exception_type, message
):
    class FailedAllocation(_FakeComfy):
        def get_history(self, prompt_id=None, **_kwargs):
            return {
                prompt_id: {
                    "status": {
                        "status_str": "error",
                        "completed": False,
                        "messages": [
                            [
                                "execution_error",
                                {
                                    "exception_type": exception_type,
                                    "exception_message": message,
                                },
                            ]
                        ],
                    }
                }
            }

    client = FailedAllocation(tmp_path)
    backend = _backend(client, ram_gb=0.5)
    repository, queue, service, _controller = _build_stack(tmp_path, [backend])
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    )
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "navy").save(source)
    try:
        job_id = controller.submit_video_workflow_job(
            source_image_path=source,
            form_data={
                "workflow_id": "wan22_ti2v_5b_i2v_v1",
                "workflow_version": "1.2.0",
                "prompt": "waves",
                "seed": 7,
                "frame_count": 17,
            },
        )
        queued = repository.get_job(job_id)
        assert queued.status is JobStatus.QUEUED and client.queued == []
        service.runner.run_once(queue.get_job(job_id))
        failed = repository.get_job(job_id)
        assert failed.status is JobStatus.FAILED
        assert message in str(failed.error_message or failed.result)
        assert exception_type in str(failed.error_message or failed.result)
        assert len(client.queued) == 1
    finally:
        service.stop()
        repository.close()


@pytest.mark.parametrize(
    "pathway, count", [("single", 1), ("batch", 2), ("experiment", 2), ("sequence", 1)]
)
def test_all_admission_paths_persist_njrs_despite_transient_memory_pressure(
    tmp_path, pathway, count
):
    client = _FakeComfy(tmp_path)
    repository, queue, service, _controller = _build_stack(tmp_path, [_backend(client)])
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output")),
        preflight_probes=lambda: _probes(ram_gb=0.5, vram=(12282, 500)),
    )
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "navy").save(source)
    form = {
        "workflow_id": "wan22_ti2v_5b_i2v_v1",
        "workflow_version": "1.3.0",
        "prompt": "waves",
        "seed": 7,
        "frame_count": 17,
    }
    if pathway == "experiment":
        form.update(
            workflow_id="wan_animate2_prompt_i2v_v1",
            workflow_version="1.2.0",
            experimental_opt_in=True,
            operator_controls={"reference_image_strength": "1"},
        )
    try:
        preflight = controller.workflow_preflight(form["workflow_id"], form["workflow_version"])
        assert preflight.queueable
        assert sum(g.state == "advisory" for g in preflight.gates) == 2
        if pathway == "single":
            ids = [controller.submit_video_workflow_job(source_image_path=source, form_data=form)]
        elif pathway == "batch":
            second = tmp_path / "second.png"
            Image.new("RGB", (32, 32), "red").save(second)
            selection = controller.select_batch_sources([source, second])
            plan = controller.preview_batch(sources=selection.sources, form_data=form)
            ids = controller.submit_batch(plan).job_ids
        elif pathway == "experiment":
            plan = controller.preview_experiment(
                source_image_path=source,
                form_data=form,
                variable_name="reference_image_strength",
                candidates=["1.2"],
            )
            ids = controller.submit_experiment(plan).job_ids
        else:
            ids = [
                controller.submit_sequence_job(
                    source_image_path=str(source), form_data=form, sequence_intent=_intent(2)
                )
            ]
        assert len(ids) == count and client.queued == []
        for job_id in ids:
            stored = repository.get_job_model(job_id)
            assert stored.status is JobStatus.QUEUED
            record = stored._normalized_record
            assert record.config["video_workflow"]["workflow_id"] == form["workflow_id"]
            assert record.config["video_workflow"]["workflow_version"] == form["workflow_version"]
        assert len(queue.list_jobs()) == count
    finally:
        service.stop()
        repository.close()
