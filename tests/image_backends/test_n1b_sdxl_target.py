"""N1b: SDXL-only features warn for an unclassified checkpoint, and observed runs outrank registry evidence."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.image_backends.sdxl_target as st
from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.model_policy import (
    EVIDENCE_ACCEPTED_UNVERIFIED,
    EVIDENCE_OBSERVED,
    EVIDENCE_REGISTRY,
    resolve_model_policy,
    sdxl_policy_with_evidence,
)
from src.learning.model_capabilities import compatible_context, policy_context
from src.pipeline.policy_warnings import CODE_IMAGE_MODEL_FAMILY_UNVERIFIED, CONTRACT


def _compat(family: str, status: str = "resolved", architecture: str | None = None):
    return SimpleNamespace(
        status=SimpleNamespace(value=status),
        family=SimpleNamespace(value=family) if family else None,
        structural_error=None,
        checkpoint_architecture=architecture,
    )


def _policy(compat):
    return resolve_model_policy("model.safetensors", family_lookup=lambda _name: compat)


SDXL = _policy(_compat("sdxl"))
SD1 = _policy(_compat("sd1"))
UNKNOWN = resolve_model_policy("model.safetensors")  # no registry record at all
CONFLICTING = _policy(_compat("", status="conflicting"))
REFINER = _policy(_compat("sdxl", architecture="sdxl_refiner"))
KLEIN = resolve_model_policy(latest_klein_profile().transformer.filename)


def _assess(
    policy,
    *,
    runs: int = 0,
    operation: str = st.OP_TXT2IMG_CONTROLNET,
    model: str = "model.safetensors",
):
    return st.assess_sdxl_target(
        policy,
        model=model,
        operation=operation,
        backend_id="forge_webui",
        feature="ControlNet",
        observed=(lambda _m, _o, _b: runs),
    )


def test_registry_sdxl_is_verified_and_reports_observed_runs():
    target = _assess(SDXL, runs=3)
    assert target.status is st.TargetStatus.REGISTRY and target.warning is None
    assert target.policy.evidence == EVIDENCE_REGISTRY
    assert "ran 3 times here" in target.evidence_text()


@pytest.mark.parametrize("policy,phrase", [
    (UNKNOWN, "has no record of the header"),
    (CONFLICTING, "headers disagree"),
    (REFINER, "refiner or inpaint variant"),
])  # fmt: skip
def test_an_unclassified_checkpoint_is_a_warning_with_why_and_fix(policy, phrase):
    target = _assess(policy)
    assert target.allowed and target.status is st.TargetStatus.WARNING
    assert target.policy.family == "sdxl" and target.policy.evidence == EVIDENCE_ACCEPTED_UNVERIFIED
    warning = target.warning
    assert warning is not None and warning.code == CODE_IMAGE_MODEL_FAMILY_UNVERIFIED
    assert phrase in warning.why
    assert "Queue runs it anyway" in warning.fix and "select an SDXL checkpoint" in warning.fix
    if policy is CONFLICTING:
        assert "duplicate checkpoint file" in warning.fix
    else:
        assert "Quick scan" in warning.fix


def test_observed_runs_make_an_unclassified_checkpoint_verified_without_a_warning():
    target = _assess(UNKNOWN, runs=2)
    assert target.status is st.TargetStatus.OBSERVED and target.warning is None
    assert target.policy.evidence == EVIDENCE_OBSERVED
    assert target.evidence_text() == "model.safetensors: ran 2 times here (ControlNet txt2img)."


def test_a_positively_identified_other_family_is_a_real_block_with_a_fix():
    target = _assess(SD1)
    assert not target.allowed and target.status is st.TargetStatus.BLOCKED
    assert "Only SDXL checkpoints can be used for ControlNet" in target.block
    assert "Select an SDXL checkpoint" in target.block and "Quick scan" in target.block
    with pytest.raises(ValueError, match="Only SDXL checkpoints"):
        target.require()


def test_observed_runs_turn_a_wrong_family_block_into_a_warning_by_owner_decision_q1():
    """Owner decision Q1 (2026-11-26, "Warn, then run")."""
    assert st.OBSERVED_VS_REGISTRY_FAMILY == "warn"
    target = _assess(SD1, runs=4)
    assert target.allowed and target.status is st.TargetStatus.WARNING and target.observed_runs == 4
    assert target.policy.evidence == EVIDENCE_ACCEPTED_UNVERIFIED
    assert "says SD1 (unqualified), but it ran 4 times here" in target.warning.title
    assert (
        "does not prove the family" in target.warning.why
        and "Queue runs it anyway" in target.warning.fix
    )


def test_the_test_only_q1_modes(monkeypatch):
    monkeypatch.setattr(st, "OBSERVED_VS_REGISTRY_FAMILY", "verify")
    assert _assess(SD1, runs=4).status is st.TargetStatus.OBSERVED
    monkeypatch.setattr(st, "OBSERVED_VS_REGISTRY_FAMILY", "block")
    assert _assess(SD1, runs=4).status is st.TargetStatus.BLOCKED


def test_controlnet_is_judged_per_modality_by_owner_decision_q2():
    canny = st.controlnet_operation("Canny")
    assert canny == "txt2img_controlnet:canny" and st.is_operation(canny)
    runs = {canny: 3}
    observed = lambda _m, op, _b: runs.get(op, 0)  # noqa: E731
    verdicts = [
        st.assess_sdxl_target(UNKNOWN, model="m", operation=st.controlnet_operation(modality),
                              backend_id="forge_webui", feature="ControlNet", observed=observed)
        for modality in ("canny", "depth")
    ]  # fmt: skip
    assert [item.status for item in verdicts] == [st.TargetStatus.OBSERVED, st.TargetStatus.WARNING]
    assert verdicts[0].evidence_text() == "m: ran 3 times here (ControlNet canny txt2img)."
    assert st.combine(verdicts).status is st.TargetStatus.WARNING  # the weakest unit decides
    assert st.combine([verdicts[0], _assess(SD1)]).status is st.TargetStatus.BLOCKED
    with pytest.raises(ValueError):
        st.controlnet_operation("")


def test_an_exact_profile_is_never_outranked_by_observed_runs():
    target = _assess(KLEIN, runs=50)
    assert target.status is st.TargetStatus.BLOCKED and "its own model profile" in target.block


def test_unreadable_history_is_absent_evidence_never_a_pass_or_a_block():
    def broken(*_args):
        raise OSError("database is locked")

    target = st.assess_sdxl_target(
        UNKNOWN,
        model="m",
        operation=st.OP_TXT2IMG,
        backend_id="forge_webui",
        feature="X",
        observed=broken,
    )
    assert target.status is st.TargetStatus.WARNING


def test_a_frozen_substituted_policy_rechecks_to_the_same_kind_of_verdict():
    accepted = sdxl_policy_with_evidence(EVIDENCE_ACCEPTED_UNVERIFIED)
    assert _assess(accepted).status is st.TargetStatus.WARNING
    assert _assess(accepted, runs=1).status is st.TargetStatus.OBSERVED
    with pytest.raises(ValueError):
        sdxl_policy_with_evidence("no_evidence")


def test_unknown_operations_are_refused_as_programming_errors():
    with pytest.raises(ValueError, match="Unknown SDXL operation"):
        _assess(SDXL, operation="txt2vid")


def test_the_verdict_is_surface_neutral_data_for_the_phone_gateway():
    data = _assess(UNKNOWN).as_dict()
    assert data["status"] == "warning" and data["evidence"] == EVIDENCE_ACCEPTED_UNVERIFIED
    assert data["warning"]["contract"] == CONTRACT and data["warning"]["fix"]
    assert set(data) == {
        "status",
        "operation",
        "model",
        "evidence",
        "observed_runs",
        "warning",
        "block",
        "text",
    }
    blocked = _assess(SD1).as_dict()
    assert blocked["status"] == "blocked" and blocked["evidence"] == "" and blocked["block"]


def test_frozen_studies_stay_compatible_across_sdxl_evidence_tiers():
    contexts = [
        policy_context(sdxl_policy_with_evidence(evidence), "m.safetensors", "txt2img")
        for evidence in (EVIDENCE_REGISTRY, EVIDENCE_OBSERVED, EVIDENCE_ACCEPTED_UNVERIFIED)
    ]
    assert all(compatible_context(left, right) for left in contexts for right in contexts)
    unverified = policy_context(UNKNOWN, "m.safetensors", "txt2img")
    assert not compatible_context(contexts[0], unverified)
