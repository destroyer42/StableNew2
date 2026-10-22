"""PR-VID-GOV-316: Wan2.2 TI2V-5B 1.2.0 is promoted to ``approved`` (owner decision D1, 2026-10-20).

Deterministic and GPU-free. Pins what the promotion changes (1.2.0 needs no per-job opt-in, appears
in the runnable listing, is no longer labelled experimental) and what it must not change (1.0.0 and
1.1.0 stay experimental because published versions are byte-pinned, governance included; the
Wan-Animate-2 workflows stay experimental; a stored job that recorded an opt-in still runs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.video.video_workflow_intent import (
    EXPERIMENTAL_OPT_IN_FIELD,
    build_video_execution_block,
    capability_errors,
    experimental_opt_in_granted,
    form_visibility,
)
from src.video.workflow_catalog import WAN22_RUNTIME_VERSION, build_builtin_workflow_specs
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
)
from src.video.workflow_registry import WorkflowLookupError, build_default_workflow_registry
from tests.video.test_pr_vid_190_comfy_lifecycle_frame_count import _backend, _FakeManager, _request
from tests.video.test_wan22_experimental_workflow import WAN_ID, _FakeComfy

APPROVED = (WAN_ID, WAN22_RUNTIME_VERSION)
# PR-VID-WAN-324: the frames-out revision, approved by the owner on 2026-10-21 after real acceptance runs.
APPROVED_FRAMES_OUT = (WAN_ID, "1.3.0")
OLDER_TI2V = ((WAN_ID, "1.0.0"), (WAN_ID, "1.1.0"))
PROMPT_FORM = {"prompt": "the person turns slowly toward the camera"}


def _spec(workflow_id: str, version: str):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


# ---------------------------------------------------------------------------- catalog governance


def test_exactly_two_catalog_versions_are_approved_and_both_are_ti2v() -> None:
    states = {
        (spec.workflow_id, spec.workflow_version): spec.governance_state
        for spec in build_builtin_workflow_specs()
    }

    assert WAN22_RUNTIME_VERSION == "1.2.0"
    assert [key for key, state in states.items() if state == "approved"] == [
        APPROVED,
        APPROVED_FRAMES_OUT,
    ]
    assert {key for key, state in states.items() if state == "experimental"} == {
        *OLDER_TI2V,
        *(
            (wid, ver)
            for wid in (WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID)
            for ver in ("1.0.0", "1.1.0", "1.2.0")
        ),
    }
    assert len(states) == 10  # the frames-out TI2V-5B revision is the only addition


def test_the_runnable_listing_is_the_approved_version_and_the_offerable_listing_is_unchanged() -> (
    None
):
    registry = build_default_workflow_registry()

    assert [
        (s.workflow_id, s.workflow_version) for s in registry.list_specs_for_backend("comfy")
    ] == [APPROVED, APPROVED_FRAMES_OUT]
    assert len(registry.list_offerable_specs("comfy")) == 10


def test_registry_runs_the_approved_version_without_opt_in_and_keeps_older_ones_gated() -> None:
    registry = build_default_workflow_registry()

    spec = registry.get(WAN_ID, WAN22_RUNTIME_VERSION)  # no allow_experimental
    assert spec.governance_state == "approved" and not spec.is_experimental and spec.is_runnable
    for workflow_id, version in OLDER_TI2V:
        with pytest.raises(WorkflowLookupError, match="explicit experimental opt-in"):
            registry.get(workflow_id, version)
        assert registry.get(workflow_id, version, allow_experimental=True).is_experimental
    for workflow_id in (WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID):
        with pytest.raises(WorkflowLookupError, match="explicit experimental opt-in"):
            registry.get(workflow_id, "1.2.0")


def test_the_promoted_version_no_longer_labels_itself_experimental_and_older_ones_do() -> None:
    promoted = _spec(*APPROVED)

    assert "experimental" not in promoted.display_name.lower()
    assert "experimental" not in promoted.description.lower()
    assert promoted.governance_notes.startswith("APPROVED")
    for key in OLDER_TI2V:
        older = _spec(*key)
        assert older.display_name.endswith("(Experimental)")
        assert older.governance_notes.startswith("EXPERIMENTAL")


def test_promotion_changed_governance_text_only_not_the_graph_files_floors_or_policies() -> None:
    older, promoted = _spec(WAN_ID, "1.1.0"), _spec(*APPROVED)

    assert promoted.backend_defaults["prompt_template"] == older.backend_defaults["prompt_template"]
    assert promoted.dependency_specs == older.dependency_specs
    assert promoted.input_bindings == older.input_bindings
    assert promoted.accepted_controls == older.accepted_controls
    for key in (
        "resource_readiness",
        "runtime_policy",
        "frame_count_policy",
        "history_timeout_seconds",
    ):
        assert promoted.backend_defaults[key] == older.backend_defaults[key]
    assert (
        promoted.backend_defaults["resource_readiness"]["min_available_to_comfy_vram_mib"] == 10000
    )
    assert promoted.backend_defaults["resource_readiness"]["min_available_ram_gb"] == 16.0


# ---------------------------------------------------------------------------- admission intent


def test_an_approved_workflow_is_admitted_without_an_opt_in() -> None:
    spec = _spec(*APPROVED)

    assert capability_errors(spec, {**PROMPT_FORM}) == []
    assert capability_errors(spec, {**PROMPT_FORM, EXPERIMENTAL_OPT_IN_FIELD: False}) == []
    assert form_visibility(spec)["experimental"] is False


@pytest.mark.parametrize(
    ("workflow_id", "version"),
    [*OLDER_TI2V, (WAN_ANIMATE2_PROMPT_ID, "1.2.0")],
)
def test_a_still_experimental_workflow_is_refused_without_its_opt_in(
    workflow_id: str, version: str
) -> None:
    spec = _spec(workflow_id, version)
    form = {**PROMPT_FORM, "pose_video_path": ""}

    errors = capability_errors(spec, form)
    assert any("Enable experimental workflow" in error for error in errors)
    ticked = capability_errors(spec, {**form, EXPERIMENTAL_OPT_IN_FIELD: True})
    assert not any("Enable experimental workflow" in error for error in ticked)
    assert form_visibility(spec)["experimental"] is True


def test_new_jobs_for_an_approved_workflow_record_no_opt_in_even_if_a_stale_form_ticked_one() -> (
    None
):
    approved, older = _spec(*APPROVED), _spec(WAN_ID, "1.1.0")
    ticked = {**PROMPT_FORM, EXPERIMENTAL_OPT_IN_FIELD: True}

    assert experimental_opt_in_granted(approved, ticked) is False
    assert build_video_execution_block(approved, ticked)[EXPERIMENTAL_OPT_IN_FIELD] is False
    # An experimental version keeps recording exactly what the operator ticked.
    assert build_video_execution_block(older, ticked)[EXPERIMENTAL_OPT_IN_FIELD] is True
    assert build_video_execution_block(older, PROMPT_FORM)[EXPERIMENTAL_OPT_IN_FIELD] is False


# ---------------------------------------------------------------------------- backend governance


def _run(tmp_path: Path, *, version: str, opt_in: bool):
    tmp_path.mkdir(parents=True, exist_ok=True)
    manager, client = _FakeManager(), _FakeComfy(tmp_path)
    request = _request(tmp_path, version=version)
    request.experimental_opt_in = opt_in
    try:
        result = _backend(client, manager).execute(None, request)
    except Exception as exc:
        return exc, client, manager
    return result, client, manager


def test_the_backend_runs_the_approved_version_without_an_opt_in(tmp_path: Path) -> None:
    result, client, _manager = _run(tmp_path, version=WAN22_RUNTIME_VERSION, opt_in=False)

    assert not isinstance(result, Exception), result
    assert len(client.queued) == 1


def test_a_job_recorded_with_an_opt_in_before_the_promotion_still_runs_on_the_approved_version(
    tmp_path: Path,
) -> None:
    result, client, _manager = _run(tmp_path, version=WAN22_RUNTIME_VERSION, opt_in=True)

    assert not isinstance(result, Exception), result
    assert len(client.queued) == 1


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_older_versions_still_need_the_recorded_opt_in_and_replay_with_it(
    tmp_path: Path, version: str
) -> None:
    refused, client, manager = _run(tmp_path / "off", version=version, opt_in=False)
    assert isinstance(refused, KeyError) and "explicit experimental opt-in" in str(refused)
    assert client.queued == [] and manager.starts == 0  # refused before any runtime starts

    replayed, client, _manager = _run(tmp_path / "on", version=version, opt_in=True)
    assert not isinstance(replayed, Exception), replayed
    assert len(client.queued) == 1
