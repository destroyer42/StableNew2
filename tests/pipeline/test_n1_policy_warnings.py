"""N1 "warn, don't block": typed warnings, the recorded acceptance and the image/video warning builders."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.assets.component_evidence import ROLE_TEXT_ENCODER, ROLE_VAE
from src.image_backends.model_policy_warnings import is_policy_refusal, unqualified_model_warning
from src.image_backends.model_readiness import (
    DependencyRequirement,
    ModelReadiness,
    ReadinessStatus,
)
from src.pipeline.policy_warnings import (
    ACCEPTED_WARNINGS_KEY,
    CODE_IMAGE_MODEL_UNQUALIFIED,
    CODE_VIDEO_EXPERIMENTAL,
    SURFACE_DESKTOP,
    SURFACE_PHONE,
    PolicyWarning,
    accepted_warning_keys,
    is_accepted,
    merge_accepted_warnings,
    unaccepted,
    with_accepted_warnings,
)
from src.video.workflow_registry import build_default_workflow_registry
from src.video.workflow_warnings import experimental_workflow_warning
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

WARNING = PolicyWarning(
    CODE_VIDEO_EXPERIMENTAL, "wf@1.0.0", "WF is experimental.", "Why.", "Fix.", "gate"
)


def test_a_warning_is_plain_data_that_round_trips_for_any_surface() -> None:
    data = WARNING.as_dict()
    assert data["contract"] == "policy_warning/1" and data["code"] == CODE_VIDEO_EXPERIMENTAL
    assert PolicyWarning.from_dict(data) == WARNING
    assert WARNING.text() == "WF is experimental. Why. Fix."
    with pytest.raises(ValueError):
        PolicyWarning("", "subject", "t", "w")


def test_acceptance_is_recorded_once_per_code_and_subject_with_its_surface() -> None:
    merged = merge_accepted_warnings({"other": 1}, [WARNING, WARNING], surface=SURFACE_PHONE)
    assert merged["other"] == 1
    assert [item["surface"] for item in merged[ACCEPTED_WARNINGS_KEY]] == [SURFACE_PHONE]
    assert is_accepted(merged, CODE_VIDEO_EXPERIMENTAL, "wf@1.0.0")
    again = merge_accepted_warnings(merged, [WARNING], surface=SURFACE_DESKTOP)
    assert len(again[ACCEPTED_WARNINGS_KEY]) == 1  # never duplicated, the first acceptance is kept
    other = PolicyWarning(CODE_IMAGE_MODEL_UNQUALIFIED, "m.safetensors", "t", "w")
    assert unaccepted(again, [WARNING, other]) == (other,)
    assert merge_accepted_warnings({}, [], surface=SURFACE_DESKTOP) == {}
    with pytest.raises(ValueError):
        merge_accepted_warnings({}, [WARNING], surface="tablet")


def test_an_njr_is_refrozen_with_its_accepted_warnings_and_otherwise_kept_identical() -> None:
    record = make_pipeline_njr(job_id="n1-accept", positive_prompt="a lighthouse")
    assert with_accepted_warnings(record, [], surface=SURFACE_DESKTOP) is record
    accepted = with_accepted_warnings(record, [WARNING], surface=SURFACE_DESKTOP)
    assert accepted.job_id == record.job_id and accepted.stage_chain == record.stage_chain
    assert accepted_warning_keys(accepted.extra_metadata) == {(CODE_VIDEO_EXPERIMENTAL, "wf@1.0.0")}
    assert with_accepted_warnings(accepted, [WARNING], surface=SURFACE_DESKTOP) is accepted


def test_every_experimental_catalog_workflow_has_a_warning_and_no_approved_one_does() -> None:
    specs = build_default_workflow_registry().list_offerable_specs("comfy")
    experimental = [spec for spec in specs if spec.is_experimental]
    assert experimental, "the catalog has experimental workflows"
    for spec in specs:
        warning = experimental_workflow_warning(spec, alternative="Wan2.2 I2V-A14B")
        if spec.is_experimental:
            assert (
                warning is not None
                and warning.subject == f"{spec.workflow_id}@{spec.workflow_version}"
            )
            assert "Queue runs it anyway" in warning.fix and "Wan2.2 I2V-A14B" in warning.fix
        else:
            assert warning is None


def _readiness(
    status: ReadinessStatus, *, catalog: tuple[str, ...] | None, deps=()
) -> ModelReadiness:
    return ModelReadiness(
        "flux-2-klein-base-9b.safetensors",
        status,
        "reason",
        (
            "This is a multi-component flux2 transformer: it needs a text encoder and a VAE supplied separately. "
            "StableNew has no exact qualified execution profile for it.",
            "Not found in Forge's module catalog: text encoder.",
            "Physical qualification (PR-IMG-MODELS-151) is required before it can run.",
        ),
        architecture="flux2_dit",
        dependencies=deps,
        catalog_names=catalog,
        selected_modules=None if catalog is None else (),
    )


def test_an_unqualified_model_warning_says_what_is_missing_and_which_folder_it_goes_in(
    tmp_path,
) -> None:
    deps = (
        DependencyRequirement(ROLE_TEXT_ENCODER, "a text encoder with hidden size 4096", 4096),
        DependencyRequirement(
            ROLE_VAE, "a VAE with 32 latent channels", 32, candidates=("flux2-vae.safetensors",)
        ),
    )
    readiness = _readiness(
        ReadinessStatus.DEPENDENCIES_INCOMPLETE, catalog=("flux2-vae.safetensors",), deps=deps
    )
    warning = unqualified_model_warning(readiness, webui_root=tmp_path)
    assert warning is not None and warning.code == CODE_IMAGE_MODEL_UNQUALIFIED
    assert warning.subject == "flux-2-klein-base-9b.safetensors"
    assert (
        "Physical qualification" not in warning.text()
    )  # the old refusal tail is replaced by a fix
    assert "Missing: a text encoder with hidden size 4096" in warning.fix
    assert str(tmp_path / "models" / "text_encoder") in warning.fix
    assert "ask Claude to find and download it into that folder" in warning.fix
    assert "select it in Forge's VAE / Text Encoder menu" in warning.fix  # listed but not selected
    assert "leaves Forge's module selection exactly as it is" in warning.fix


def test_without_forge_state_the_warning_points_at_check_readiness_and_the_folders() -> None:
    deps = (DependencyRequirement(ROLE_TEXT_ENCODER, "a separate text encoder", None),)
    warning = unqualified_model_warning(
        _readiness(ReadinessStatus.UNAVAILABLE_OR_STALE, catalog=None, deps=deps)
    )
    assert warning is not None
    assert "Check readiness" in warning.fix and "Forge's models/text_encoder folder" in warning.fix


def test_a_file_that_is_not_a_checkpoint_stays_a_real_block() -> None:
    readiness = ModelReadiness(
        "vae.safetensors", ReadinessStatus.NOT_A_CHECKPOINT, "component_not_checkpoint"
    )
    assert readiness.blocks_dispatch is True
    assert not is_policy_refusal(readiness) and unqualified_model_warning(readiness) is None
    harmless = SimpleNamespace(blocks_dispatch=False, status=ReadinessStatus.NOT_DEPENDENCY_BEARING)
    assert not is_policy_refusal(harmless)  # type: ignore[arg-type]


def test_queue_records_the_model_warning_the_picker_showed_and_nothing_else() -> None:
    from src.controller.pipeline_controller_services.queue_submission_service import (
        QueueSubmissionService,
    )
    from src.image_backends.model_policy_warnings import publish_shown_warnings, shown_warning_for

    shown = PolicyWarning(
        CODE_IMAGE_MODEL_UNQUALIFIED, "flux-2-klein-base-9b.safetensors", "t", "why", "fix"
    )
    publish_shown_warnings({"flux-2-klein-base-9b.safetensors [abc123]": shown})
    try:
        assert (
            shown_warning_for("FLUX-2-klein-base-9b") == shown
        )  # basename, extension and hash insensitive
        submitted: list = []
        service = QueueSubmissionService(
            job_service=SimpleNamespace(
                submit_njrs=lambda records, policy: submitted.extend(records) or ["a", "b"]
            )
        )
        warned = make_pipeline_njr(
            job_id="n1-warned",
            stage_chain=(make_stage_config("txt2img", model="flux-2-klein-base-9b.safetensors"),),
        )
        plain = make_pipeline_njr(
            job_id="n1-plain", stage_chain=(make_stage_config("txt2img", model="sdxl.safetensors"),)
        )
        count = service.submit_normalized_jobs(
            [warned, plain],
            can_enqueue_learning_jobs=lambda _n: (True, ""),
            is_queue_submission_blocked=lambda: False,
            sort_jobs_by_model=lambda records: records,
        )
        assert count == 2
        by_id = {record.job_id: record for record in submitted}
        assert accepted_warning_keys(by_id["n1-warned"].extra_metadata) == {shown.key}
        assert (
            by_id["n1-warned"].extra_metadata[ACCEPTED_WARNINGS_KEY][0]["surface"]
            == SURFACE_DESKTOP
        )
        assert by_id["n1-plain"] is plain  # an ordinary job keeps its exact record
    finally:
        publish_shown_warnings({})
