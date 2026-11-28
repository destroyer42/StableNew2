"""LTX-2.5 as an attested experimental option (owner decision 2026-11-28, VID-CAND-LTX25).

Queueing an LTX-2.5 job needs the operator's per-job attestation; it is frozen into the job's provenance, kept by
Replay and copied into the clip manifest.  Nothing inspects the image or the prompt.  Real builder, controller,
JobService and repository; a fake Comfy client for the manifest.  No GPU, Comfy process, FFmpeg, model or network.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.job_service import JobService
from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.policy_warnings import CODE_VIDEO_EXPERIMENTAL, CODE_VIDEO_LICENCE_RESTRICTION
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.video import workflow_picker as picker
from src.video.licence_attestation import (
    ATTESTATION_KEY,
    LTX25_ATTESTATION_TEXT,
    LTX25_ATTESTATION_VERSION,
    attestation_record,
    declared_attestation,
    recorded_attestation,
    with_attestation,
    workflow_ids_of,
)
from src.video.workflow_admission import require_workflow_admission
from src.video.workflow_catalog_ltx25 import (
    LTX25_AUDIO_ID,
    LTX25_ID,
    LTX25_IDS,
    LTX25_LICENCE_WARNING,
    LTX25_VERSION,
    LTX25_VERSIONS,
)
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION
from tests.video.test_vid_cand_ltx25 import FRAMES, SAVE_FRAMES_NODE, _info, _request
from tests.video.test_vid_clip_370_candidate_specs import _a14b_backend, _FramesFake

AT = datetime(2026, 11, 28, 12, 30, tzinfo=UTC)
OWNER_TEXT = (
    "LTX-2.5: explicit content may violate its license. I confirm this source and prompt are not "
    "sexually explicit."
)


def _attested() -> dict[str, Any]:
    declared = declared_attestation(LTX25_ID)
    assert declared is not None
    return attestation_record(declared, at=AT)


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "portrait.png"
    Image.new("RGB", (576, 1024), (20, 120, 200)).save(path)
    return path


def _form(workflow_id: str = LTX25_ID, **extra: Any) -> dict[str, Any]:
    ltx = workflow_id in LTX25_IDS
    return {
        "workflow_id": workflow_id,
        "workflow_version": LTX25_VERSION if ltx else WAN_A14B_VERSION,
        "prompt": "she waves",
        "seed": "7",
        "frame_count": 25 if ltx else 81,
        "experimental_opt_in": ltx,
        **extra,
    }


def _controller(tmp_path: Path, jobs: Any) -> VideoWorkflowController:
    app = SimpleNamespace(job_service=jobs, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app)


class _Jobs:
    """Runs the real admission check, then records what would have been queued."""

    def __init__(self) -> None:
        self.njrs: list[Any] = []

    def submit_njrs(self, njrs, policy):
        for njr in njrs:
            require_workflow_admission(njr)
        self.njrs.extend(njrs)
        return [str(njr.job_id) for njr in njrs]


def _build(tmp_path: Path, workflow_id: str = LTX25_ID) -> Any:
    builder = _controller(tmp_path, _Jobs())._njr_builder
    form = _form(workflow_id)
    return builder.build_job(form, builder.freeze_inputs(_source(tmp_path), form)).njr


# --- what is declared and what the picker offers -------------------------------------------------


def test_both_ltx_ids_declare_the_owners_wording_and_nothing_else_does() -> None:
    assert LTX25_ATTESTATION_TEXT == OWNER_TEXT
    for workflow_id in LTX25_IDS:
        declared = declared_attestation(workflow_id)
        assert declared is not None
        assert (declared.version, declared.text) == (LTX25_ATTESTATION_VERSION, OWNER_TEXT)
    others = {
        spec.workflow_id for spec in DefaultWorkflowRegistryPort().list_specs_for_backend("comfy")
    } - set(LTX25_IDS)
    assert WAN_A14B_ID in others
    assert all(declared_attestation(workflow_id) is None for workflow_id in others)


def test_the_sentence_and_the_licence_warning_are_one_statement() -> None:
    assert LTX25_ATTESTATION_TEXT.startswith(LTX25_LICENCE_WARNING["title"])


@pytest.mark.parametrize("version", LTX25_VERSIONS)
def test_every_registered_version_needs_it(tmp_path, version: str) -> None:
    builder = _controller(tmp_path, _Jobs())._njr_builder
    form = _form(workflow_version=version)
    njr = builder.build_job(form, builder.freeze_inputs(_source(tmp_path), form)).njr

    with pytest.raises(ValueError, match="not sexually explicit"):
        require_workflow_admission(njr)


def test_ltx_is_offered_only_with_show_experimental_and_is_never_the_default(tmp_path) -> None:
    records = _controller(tmp_path, _Jobs()).list_workflow_specs()
    hidden = picker.offered_workflow_ids(records, show_experimental=False)
    shown = picker.offered_workflow_ids(records, show_experimental=True)

    for workflow_id in LTX25_IDS:
        assert workflow_id not in hidden and workflow_id in shown
        [record] = [item for item in records if item["workflow_id"] == workflow_id]
        assert record["experimental"] and not record["make_video_default"]
        assert picker.picker_tier(record).tier == picker.TIER_EXPERIMENTAL_ONLY
        assert "confirmation" in picker.picker_tier(record).reason
    assert picker.recommended_workflow_id(records) not in LTX25_IDS


# --- the requirement at Queue ---------------------------------------------------------------------


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_queue_refuses_an_ltx_job_without_the_attestation(tmp_path, workflow_id: str) -> None:
    njr = _build(tmp_path, workflow_id)

    with pytest.raises(ValueError, match="not sexually explicit.*Nothing was queued"):
        require_workflow_admission(njr)

    require_workflow_admission(with_attestation(njr, _attested()))


def test_the_record_is_attested_the_text_version_and_the_time(tmp_path) -> None:
    njr = with_attestation(_build(tmp_path), _attested())

    assert dict(njr.extra_metadata[ATTESTATION_KEY]) == {
        "attested": True,
        "text_version": LTX25_ATTESTATION_VERSION,
        "attested_at": "2026-11-28T12:30:00+00:00",
    }


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"attested": False, "text_version": LTX25_ATTESTATION_VERSION, "attested_at": "now"},
        {"attested": True, "text_version": "an-older-text", "attested_at": "now"},
        {"attested": True, "text_version": LTX25_ATTESTATION_VERSION, "attested_at": ""},
    ],
)
def test_an_incomplete_or_outdated_confirmation_is_not_recorded(tmp_path, record) -> None:
    njr = _build(tmp_path)

    assert with_attestation(njr, record) is njr


def test_another_engine_never_records_it_and_is_queued_as_before(tmp_path) -> None:
    njr = _build(tmp_path, WAN_A14B_ID)

    assert with_attestation(njr, _attested()) is njr
    require_workflow_admission(njr)


def test_a_sequence_segment_on_ltx_needs_it_too() -> None:
    record = SimpleNamespace(
        config={
            "video_workflow": {
                "workflow_id": "hunyuan_video15_i2v_480p_8step_v1",
                "sequence_metadata": {
                    "segments": [
                        {"workflow_id": "hunyuan_video15_i2v_480p_8step_v1"},
                        {"workflow_id": LTX25_AUDIO_ID},
                    ]
                },
            }
        }
    )

    assert LTX25_AUDIO_ID in workflow_ids_of(record)
    assert declared_attestation(*workflow_ids_of(record)) is not None


def test_no_other_check_applies_and_nothing_reads_the_image_or_the_prompt(tmp_path) -> None:
    """The source file is gone and the prompt is arbitrary: only the attestation and opt-in decide."""

    njr = with_attestation(_build(tmp_path), _attested())
    for path in (tmp_path / "portrait.png", *map(Path, njr.input_image_paths)):
        path.unlink()
    unread = replace(njr, workload=replace(njr.workload, positive_prompt="anything at all"))

    require_workflow_admission(unread)

    warnings = [item["code"] for item in unread.extra_metadata["accepted_warnings"]]
    assert warnings == [CODE_VIDEO_EXPERIMENTAL, CODE_VIDEO_LICENCE_RESTRICTION]


# --- every desktop queue path ---------------------------------------------------------------------


def test_single_queue_records_the_forms_confirmation(tmp_path) -> None:
    jobs = _Jobs()
    controller = _controller(tmp_path, jobs)
    source = _source(tmp_path)

    with pytest.raises(ValueError, match="not sexually explicit"):
        controller.submit_video_workflow_job(source_image_path=source, form_data=_form())
    assert jobs.njrs == []

    form = _form(**{ATTESTATION_KEY: _attested()})
    controller.submit_video_workflow_job(source_image_path=source, form_data=form)

    [njr] = jobs.njrs
    assert recorded_attestation(njr.extra_metadata) == _attested()
    assert ATTESTATION_KEY not in form  # never kept for a later Queue


def test_batch_queue_records_it_on_every_job(tmp_path) -> None:
    from src.video.video_workflow_batch import BatchRefused, BatchSource

    jobs = _Jobs()
    controller = _controller(tmp_path, jobs)
    paths = []
    for index in range(2):
        path = tmp_path / f"source-{index}.png"
        Image.new("RGB", (576, 1024), (index * 90, 120, 200)).save(path)
        paths.append(path)
    plan = controller.preview_batch(
        sources=[BatchSource(str(path)) for path in paths], form_data=_form()
    )
    assert plan.eligible and jobs.njrs == []  # a preview needs no confirmation

    with pytest.raises(BatchRefused, match="not sexually explicit"):
        controller.submit_batch(plan)
    controller.submit_batch(plan, attestation=_attested())

    assert [recorded_attestation(njr.extra_metadata) for njr in jobs.njrs] == [_attested()] * 2


def test_ltx_has_no_one_variable_experiment_to_confirm(tmp_path) -> None:
    """Experiments compare a declared operator control and LTX-2.5 declares none, so that Queue cannot run it."""

    records = _controller(tmp_path, _Jobs()).list_workflow_specs()

    assert [r["operator_controls"] for r in records if r["workflow_id"] in LTX25_IDS] == [
        None,
        None,
    ]


def test_sequence_queue_records_it(tmp_path) -> None:
    jobs = _Jobs()
    controller = _controller(tmp_path, jobs)

    controller.submit_sequence_job(
        source_image_path=str(_source(tmp_path)),
        form_data=_form(**{ATTESTATION_KEY: _attested()}),
        sequence_intent={
            "segments": [
                {"prompt": "she waves", "frame_count": 25},
                {"prompt": "she turns", "frame_count": 25},
            ]
        },
    )

    [njr] = jobs.njrs
    assert recorded_attestation(njr.extra_metadata) == _attested()


def test_eval_run_records_it_on_the_ltx_arm_only(tmp_path) -> None:
    from src.video.video_eval_run import BuiltEvalJob, VideoEvalRunService
    from src.video.video_eval_suite import ARM_BACKEND_WORKFLOW, EvalArm, EvalCase, EvalSuite
    from src.video.video_workflow_njr_builder import sha256_file

    builder = _controller(tmp_path, _Jobs())._njr_builder
    source = _source(tmp_path)
    case = EvalCase("case-1", source, sha256_file(source), "she waves", "")
    arms = tuple(
        EvalArm(name, name, ARM_BACKEND_WORKFLOW, {"workflow_id": workflow_id})
        for name, workflow_id in (("ltx", LTX25_ID), ("a14b", WAN_A14B_ID))
    )
    suite = EvalSuite("attest", None, "0" * 64, "attest", (case,), arms, 5, "a14b")

    def build(case: Any, arm: Any, seed: int) -> BuiltEvalJob:
        form = _form(arm.overrides["workflow_id"], seed=seed)
        built = builder.build_job(form, builder.freeze_inputs(case.image_path, form))
        return BuiltEvalJob(built.njr, built.seed, built.frame_count)

    service = VideoEvalRunService(builders={ARM_BACKEND_WORKFLOW: build})
    plan = service.plan(suite)
    assert plan.eligible, plan.errors
    jobs = _Jobs()

    service.admit(plan, jobs, output_root=tmp_path / "output", attestation=_attested())

    assert [recorded_attestation(njr.extra_metadata) is not None for njr in jobs.njrs] == [
        True,
        False,
    ]


# --- durable queue, Replay and manifest -----------------------------------------------------------


def test_the_repository_keeps_it_and_replay_keeps_it(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        jobs = JobService(JobQueue(repository=repository), runner=Mock(is_running=lambda: True))
        njr = _build(tmp_path)
        with pytest.raises(ValueError, match="not sexually explicit"):
            jobs.submit_njrs([njr])
        assert not repository.list_jobs()

        jobs.submit_njrs([with_attestation(njr, _attested())])
        stored = repository.get_job_model(njr.job_id)._normalized_record
        assert recorded_attestation(stored.extra_metadata) == _attested()

        replay = compile_replay_intent(ReplayIntent(stored))
        jobs.submit_njrs([replay])  # no new confirmation: the record travels with the job

        child = repository.get_job_model(replay.job_id)._normalized_record
        assert recorded_attestation(child.extra_metadata) == _attested()
    finally:
        repository.close()


@pytest.fixture
def _no_encode(monkeypatch):
    from tests.video.test_vid_clip_370_candidate_specs import _fake_export

    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


@pytest.mark.parametrize("attested", [True, False])
def test_the_clip_manifest_carries_the_jobs_record(tmp_path, _no_encode, attested: bool) -> None:
    client = _FramesFake(tmp_path, save_node=SAVE_FRAMES_NODE, info=_info(), frames=FRAMES)
    request = _request(tmp_path, LTX25_ID)
    request.context_metadata = {"provenance": {ATTESTATION_KEY: _attested()} if attested else {}}

    result = _a14b_backend(client, tmp_path).execute(None, request)

    assert result is not None
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest.get(ATTESTATION_KEY) == (_attested() if attested else None)


# --- History retry --------------------------------------------------------------------------------


def test_a_retry_of_an_ltx_job_that_never_recorded_it_says_so_early(tmp_path) -> None:
    from src.controller.batch_operations_service import BatchOperationsService

    service = object.__new__(BatchOperationsService)
    service._workflow_registry = DefaultWorkflowRegistryPort()
    njr = _build(tmp_path)

    assert "not sexually explicit" in service._workflow_problem(njr)
    assert service._workflow_problem(with_attestation(njr, _attested())) is None
