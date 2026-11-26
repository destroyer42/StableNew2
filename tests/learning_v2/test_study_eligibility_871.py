"""LEARN-NAV-871: the study eligibility projection delegates to each study's own target check and adds no rule."""

from __future__ import annotations

import copy
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.model_policy import (
    EVIDENCE_NONE,
    EVIDENCE_REGISTRY,
    _unverified_policy,
    resolve_model_policy,
)
from src.image_backends.sdxl_target import SdxlTarget
from src.learning import study_catalog
from src.learning.compatibility_probe import suggest_recipes
from src.learning.embedding_experiment import POSITIVE
from src.learning.embedding_experiment import require_target as embedding_target
from src.learning.learning_controller_services.compatibility_probe import require_probe_target
from src.learning.lora_composition import require_target as lora_target
from src.learning.model_capabilities import project_learning_capabilities
from src.learning.model_comparison import candidate_target_check
from src.learning.prompt_model_matrix import require_matrix_baseline
from src.learning.prompt_slot_experiment import require_target as slot_target
from src.learning.study_eligibility import describe, eligible_studies
from src.learning.two_axis_grid import _eligible as grid_policy_check
from src.learning.two_axis_grid import require_plain_txt2img
from tests.learning_v2.test_model_comparison_140 import SDXL, baseline, family


def _policies():
    return {
        "registry_sdxl": resolve_model_policy(SDXL, family_lookup=family),
        "unverified_generic_sdxl": _unverified_policy("sdxl", EVIDENCE_REGISTRY),
        "unverified_generic_no_evidence": _unverified_policy("sdxl", EVIDENCE_NONE),
        "exact_profile": resolve_model_policy(latest_klein_profile().transformer.filename),
        "unknown_family": resolve_model_policy("mystery.safetensors"),
    }


POLICIES = _policies()


def _raised(check) -> str:
    try:
        outcome = check()
    except ValueError as exc:
        return str(exc)
    if isinstance(outcome, SdxlTarget):  # N1b: a passing SDXL target (possibly with a warning)
        return ""
    return str(outcome or "")


def _own_verdict(slug: str, policy, config) -> str:
    """Each study's own target check, called the way its own engine calls it (never through the projection)."""
    if slug == "prompt_slot":
        return _raised(lambda: slot_target(policy, config))
    if slug == "lora_composition":
        return _raised(lambda: lora_target(policy, config))
    if slug == "embedding_experiment":
        return _raised(lambda: embedding_target(policy, config, POSITIVE))
    if slug == "model_comparison":
        return _raised(lambda: candidate_target_check(policy, config))
    if slug == "prompt_model_matrix":
        return _raised(lambda: candidate_target_check(policy, config)) or _raised(
            lambda: require_matrix_baseline(config)
        )
    if slug == "two_axis_grid":
        return _raised(lambda: grid_policy_check(policy, config)) or _raised(
            lambda: require_plain_txt2img(config)
        )
    if slug == "compatibility_probe":
        spec = {"recipes": [r.to_dict() for r in suggest_recipes(family=str(policy.family))]}
        return _raised(lambda: require_probe_target(policy, {}, spec))
    raise AssertionError(slug)


@pytest.mark.parametrize("name", sorted(POLICIES))
def test_each_verdict_and_message_equals_the_studys_own_target_check(name):
    policy = POLICIES[name]
    config = baseline()
    config["prompt_optimizer"] = {"enabled": False}
    result = eligible_studies(policy, config, {})
    assert [s.slug for s in result.studies] == list(study_catalog.slugs())
    for study in result.studies:
        if study.slug == "controlled_variable":
            continue
        own = _own_verdict(study.slug, policy, config)
        assert study.reason == own, (name, study.slug)
        assert study.available is (own == "")


@pytest.mark.parametrize("name", sorted(POLICIES))
def test_the_models_variables_are_the_capability_projections_own(name):
    policy = POLICIES[name]
    config = baseline()
    result = eligible_studies(policy, config, {})
    capability = project_learning_capabilities(policy, SDXL, "txt2img")
    assert result.variables == tuple(capability.variables)
    assert {n for n, _ in result.unavailable_variables} <= {
        "CFG Scale",
        "Steps",
        "Sampler",
        "Scheduler",
        "Model",
        "VAE",
        "LoRA Strength",
    }
    assert len(result.unavailable_variables) == len(capability.unavailable)
    controlled = result.get("controlled_variable")
    assert controlled.available is bool(capability.stage_supported and capability.variables)


def test_the_four_policy_shapes_land_where_the_engines_put_them():
    config = baseline()
    config["prompt_optimizer"] = {"enabled": False}
    registry = eligible_studies(POLICIES["registry_sdxl"], config, {})
    assert all(s.available for s in registry.studies)
    unverified = eligible_studies(POLICIES["unverified_generic_sdxl"], config, {})
    assert {s.slug for s in unverified.studies if not s.available} >= {
        "embedding_experiment",
        "model_comparison",
    }
    assert unverified.get(
        "prompt_slot"
    ).available  # registry evidence on SDXL is all Prompt Slot's own check asks
    exact = eligible_studies(POLICIES["exact_profile"], config, {})
    assert "nothing to probe" in exact.get("compatibility_probe").reason
    assert exact.get("model_comparison").available
    unknown = eligible_studies(POLICIES["unknown_family"], config, {})
    assert unknown.get("compatibility_probe").available
    # N1b: an unclassified checkpoint is available with the warning Preview will show.
    slot = unknown.get("prompt_slot")
    assert slot.available and slot.note.startswith(
        "Warning: ordinary.safetensors is not confirmed as SDXL."
    )


def test_a_baseline_the_study_refuses_is_reported_with_the_studys_own_text():
    config = baseline()  # the shared fixture ships with the prompt optimizer on
    assert config["prompt_optimizer"] == {"enabled": True}
    result = eligible_studies(POLICIES["registry_sdxl"], config, {})
    for slug in ("prompt_slot", "lora_composition", "embedding_experiment"):
        assert "prompt optimizer" in result.get(slug).reason.lower()
    assert result.get("prompt_model_matrix").reason == _own_verdict(
        "prompt_model_matrix", POLICIES["registry_sdxl"], config
    )
    assert "prompt optimizer" in result.get("prompt_model_matrix").reason
    assert result.get(
        "compatibility_probe"
    ).available  # a probe runs on its own optimizer-free baseline
    hires = copy.deepcopy(config)
    hires["prompt_optimizer"] = {"enabled": False}
    hires["txt2img"]["enable_hr"] = True
    assert (
        "hires fix"
        in eligible_studies(POLICIES["registry_sdxl"], hires, {}).get("two_axis_grid").reason
    )


def test_resources_add_a_note_and_never_change_a_verdict():
    config = baseline()
    config["prompt_optimizer"] = {"enabled": False}
    bare = eligible_studies(POLICIES["registry_sdxl"], config, {})
    empty = eligible_studies(POLICIES["registry_sdxl"], config, {"loras": [], "embeddings": []})
    assert [(s.slug, s.available, s.reason) for s in bare.studies] == [
        (s.slug, s.available, s.reason) for s in empty.studies
    ]
    assert "No LoRAs" in empty.get("lora_composition").note
    assert "No embeddings" in empty.get("embedding_experiment").note
    assert bare.get("lora_composition").note == ""


def test_a_supplied_live_projection_is_used_for_the_variables():
    config = baseline()
    live = SimpleNamespace(
        stage_supported=True,
        variables=("Steps",),
        unavailable=(("lora_strength", "lora_admission_required"),),
        target="Learning Target: live",
    )
    result = eligible_studies(POLICIES["registry_sdxl"], config, {}, capabilities=live)
    assert result.variables == ("Steps",) and result.target == "Learning Target: live"
    assert result.unavailable_variables == (("LoRA Strength", "no admitted LoRA is selected"),)


def test_the_owner_grouping_is_the_catalog_data():
    groups = {d.slug: (d.objective_group, d.nav_tier) for d in study_catalog.STUDIES}
    assert groups == {
        "compatibility_probe": ("works_here", "objective"),
        "controlled_variable": ("better_setting", "objective"),
        "lora_composition": ("adapter_worth_using", "objective"),
        "embedding_experiment": ("adapter_worth_using", "objective"),
        "model_comparison": ("which_i_prefer", "objective"),
        "prompt_slot": ("which_i_prefer", "objective"),
        "two_axis_grid": ("more_comparisons", "more"),
        "prompt_model_matrix": ("more_comparisons", "more"),
    }
    assert [o.label for o in study_catalog.OBJECTIVES] == [
        "Does this model work here",
        "Find a better setting",
        "Is this adapter worth using",
        "Which do I prefer",
        "More comparisons",
    ]
    assert {o.key for o in study_catalog.OBJECTIVES} == {g for g, _ in groups.values()}


def test_every_target_check_reference_resolves_and_the_catalog_stays_data_only():
    for descriptor in study_catalog.STUDIES:
        if descriptor.slug == "controlled_variable":
            assert descriptor.target_check_ref == ""
        else:
            assert callable(study_catalog.resolve_ref(descriptor.target_check_ref)), descriptor.slug


def test_describe_lists_every_study_under_its_objective_with_the_reason():
    config = baseline()
    lines = describe(eligible_studies(POLICIES["unknown_family"], config, {}))
    text = "\n".join(lines)
    for objective in study_catalog.OBJECTIVES:
        assert objective.label + ":" in text
    assert "Compatibility Probe: available" in text
    # N1b: the unclassified model no longer refuses; the shared fixture's prompt optimizer is what refuses here.
    assert "Prompt Slot: not available - Disable the prompt optimizer" in text
    config["prompt_optimizer"] = {"enabled": False}
    text = "\n".join(describe(eligible_studies(POLICIES["unknown_family"], config, {})))
    assert (
        "Prompt Slot: available - Warning: ordinary.safetensors is not confirmed as SDXL." in text
    )


def test_the_module_is_toolkit_neutral_and_does_not_import_a_gui_package():
    code = (
        "import sys; import src.learning.study_eligibility as m; "
        "from src.image_backends.model_policy import resolve_model_policy as r; "
        "m.eligible_studies(r('x'), {}, {}); "
        "bad=[n for n in sys.modules if n.split('.')[0]=='tkinter' or n.startswith('src.gui')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
