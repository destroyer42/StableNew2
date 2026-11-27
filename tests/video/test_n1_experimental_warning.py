"""N1: an experimental video workflow warns; Queue records the job's opt-in; admission refuses a job without it."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from src.pipeline.policy_warnings import (
    ACCEPTED_WARNINGS_KEY,
    CODE_VIDEO_EXPERIMENTAL,
    CODE_VIDEO_LICENCE_RESTRICTION,
    SURFACE_DESKTOP,
    SURFACE_PHONE,
    accepted_warning_records,
)
from src.video.workflow_admission import require_workflow_admission
from tests.video.test_pr_vid_motion_210_admission import _inputs, _stack

TI2V = "wan22_ti2v_5b_i2v_v1"


def _build(tmp_path, version: str, **form_extra):
    source, _clip = _inputs(tmp_path)
    form = {
        "workflow_id": TI2V,
        "workflow_version": version,
        "prompt": "a slow pan",
        "seed": "7",
        **form_extra,
    }
    controller, _service = _stack(tmp_path)
    builder = controller._njr_builder
    return builder.build_job(form, builder.freeze_inputs(source, form)).njr, controller


def _admission_record(njr, *, opt_in: bool):
    stage = copy.deepcopy(njr.config["video_workflow"])
    stage["video_execution"]["experimental_opt_in"] = opt_in
    return SimpleNamespace(
        config={"video_workflow": stage},
        stage_chain_labels=["video_workflow"],
        input_image_paths=njr.input_image_paths,
    )


def test_an_opted_in_experimental_job_records_its_accepted_warning(tmp_path) -> None:
    njr, _controller = _build(tmp_path, "1.1.0", experimental_opt_in=True)
    records = accepted_warning_records(njr.extra_metadata)
    assert [(item["code"], item["subject"], item["surface"]) for item in records] == [
        (CODE_VIDEO_EXPERIMENTAL, f"{TI2V}@1.1.0", SURFACE_DESKTOP)
    ]
    assert njr.config["video_workflow"]["video_execution"]["experimental_opt_in"] is True
    require_workflow_admission(njr)  # admitted at Queue


def test_a_phone_queue_records_the_phone_surface(tmp_path) -> None:
    njr, _controller = _build(
        tmp_path, "1.1.0", experimental_opt_in=True, warning_surface=SURFACE_PHONE
    )
    assert [item["surface"] for item in accepted_warning_records(njr.extra_metadata)] == [
        SURFACE_PHONE
    ]


def test_an_approved_job_records_no_warning(tmp_path) -> None:
    njr, _controller = _build(tmp_path, "1.3.0")
    assert ACCEPTED_WARNINGS_KEY not in njr.extra_metadata


def test_admission_refuses_any_experimental_workflow_without_its_opt_in_at_queue(tmp_path) -> None:
    njr, _controller = _build(tmp_path, "1.1.0", experimental_opt_in=True)
    require_workflow_admission(_admission_record(njr, opt_in=True))
    with pytest.raises(ValueError, match="experimental opt-in.*Nothing was queued"):
        require_workflow_admission(_admission_record(njr, opt_in=False))


def test_the_workflow_records_expose_the_warning_as_data_for_every_surface(tmp_path) -> None:
    _njr, controller = _build(tmp_path, "1.3.0")
    records = {
        (item["workflow_id"], item["workflow_version"]): item
        for item in controller.list_workflow_specs()
    }
    assert any(item["experimental"] for item in records.values())
    for item in records.values():
        warnings = item["policy_warnings"]
        if item["experimental"]:
            # LTX-2.5 also declares its licence restriction as a second warning (VID-CAND-LTX25).
            licensed = item["workflow_id"].startswith("ltx25_")
            assert [warning["code"] for warning in warnings] == [
                CODE_VIDEO_EXPERIMENTAL,
                *([CODE_VIDEO_LICENCE_RESTRICTION] if licensed else []),
            ]
            assert warnings[0]["why"] and "Queue runs it anyway" in warnings[0]["fix"]
        else:
            assert warnings == []
