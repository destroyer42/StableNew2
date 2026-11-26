"""N1b: a compiler's warning rides on the NJR for Preview and Queue records it as accepted; dispatch never refuses."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.image_backends.model_policy import resolve_model_policy
from src.image_backends.sdxl_target import OP_TXT2IMG, assess_sdxl_target
from src.learning.sdxl_study_target import (
    SNAPSHOT_WARNINGS_KEY,
    accept_frozen_warnings,
    frozen_warnings,
    warning_records,
)
from src.pipeline.policy_warnings import (
    ACCEPTED_WARNINGS_KEY,
    PENDING_WARNINGS_KEY,
    SURFACE_DESKTOP,
    accepted_warning_keys,
    pending_warnings,
    with_pending_warnings,
)
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


def _target(model: str = "mystery.safetensors"):
    return assess_sdxl_target(
        resolve_model_policy(model), model=model, operation=OP_TXT2IMG, backend_id="forge_webui",
        feature="Prompt Slot",
    )  # fmt: skip


def _njr(job_id: str = "n1b"):
    return make_pipeline_njr(
        job_id=job_id, stage_chain=(make_stage_config("txt2img", model="mystery.safetensors"),)
    )


def test_pending_warnings_are_attached_once_and_an_ordinary_job_keeps_its_record():
    plain = _njr()
    assert with_pending_warnings(plain, ()) is plain and pending_warnings(plain) == ()
    warning = _target().warning
    warned = with_pending_warnings(with_pending_warnings(plain, [warning]), [warning])
    assert pending_warnings(warned) == (warning,)
    assert warned.extra_metadata[PENDING_WARNINGS_KEY][0]["fix"] == warning.fix


def test_desktop_queue_records_compile_time_warnings_as_accepted():
    from src.controller.pipeline_controller_services.queue_submission_service import (
        QueueSubmissionService,
    )

    warning = _target().warning
    submitted: list = []
    service = QueueSubmissionService(
        job_service=SimpleNamespace(
            submit_njrs=lambda records, _p: submitted.extend(records) or ["a"]
        )
    )
    service.submit_normalized_jobs(
        [with_pending_warnings(_njr(), [warning])],
        can_enqueue_learning_jobs=lambda _n: (True, ""),
        is_queue_submission_blocked=lambda: False,
        sort_jobs_by_model=lambda records: records,
    )
    (record,) = submitted
    assert accepted_warning_keys(record.extra_metadata) == {warning.key}
    assert record.extra_metadata[ACCEPTED_WARNINGS_KEY][0]["surface"] == SURFACE_DESKTOP


def test_a_learning_study_freezes_its_warnings_and_each_queued_job_accepts_them():
    target = _target()
    snapshot = json.loads(json.dumps({SNAPSHOT_WARNINGS_KEY: warning_records([target, target])}))
    assert frozen_warnings(snapshot) == (target.warning,)
    record = accept_frozen_warnings(_njr(), snapshot)
    assert accepted_warning_keys(record.extra_metadata) == {target.warning.key}
    plain = _njr("plain")
    assert accept_frozen_warnings(plain, {}) is plain
