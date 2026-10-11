"""PR-IMG-MODELS-160: an enabled shared global positive reaches every eligible Model Comparison arm exactly once.

Real snapshot construction, frozen-arm materialization, controller Run and the real txt2img executor are used; only the
external runtime boundary (the generation backend) is replaced.
"""

from __future__ import annotations

import copy
import json
import pathlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState
from src.image_backends.forge_zimage_profile import SAMPLING_OPTIONS, ZIMAGE_PROFILE_V1
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.model_comparison import (
    digest,
    frozen_arm,
    materialize_njr,
    preview_summary,
    verify_arms_admissible,
)
from tests.learning_v2.test_model_comparison_140 import KLEIN, SDXL, controller_for
from tests.learning_v2.test_model_comparison_compat_158 import (
    ZIMAGE,
    build,
    shared_baseline,
    study,
)
from tests.learning_v2.test_model_comparison_global_prompts_140 import dispatch

GLOBAL = "studio lighting"
WEIGHTED_GLOBAL = "(studio lighting:1.3) BREAK film grain"
PROSE = "a red dress in [[place]]"
BASE = "a red dress in forest"
LEGACY_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "model_comparison_legacy_global_positive_159.json"
EXACT = [ZIMAGE, KLEIN]


def global_baseline(*, enabled=True, text=GLOBAL):
    config = shared_baseline()
    config["global_positive_prompt"] = text
    config["pipeline"]["apply_global_positive_txt2img"] = enabled
    config["prompt_optimizer"] = {"enabled": False}
    return config


def reseal(arm):
    arm["arm_sha256"] = digest({key: value for key, value in arm.items() if key != "arm_sha256"})


def arms_for(tmp_path, models, *, config=None, text=PROSE):
    _, snapshot = build(tmp_path, models=models, text=text, config=config or global_baseline())
    return snapshot, snapshot["model_comparison"]["arms"]


def operations(arm, code):
    return [op for op in arm["prompt_adaptation"]["operations"] if op["code"] == code]


def zimage_client():
    client = Mock()
    client.get_options.return_value = {
        **SAMPLING_OPTIONS,
        "sd_model_checkpoint": ZIMAGE_PROFILE_V1.transformer.filename,
        "forge_additional_modules": [asset.filename for asset in ZIMAGE_PROFILE_V1.modules],
    }
    return client


def records_for(tmp_path, models, config):
    exp = study(tmp_path, models=models, text=PROSE)
    controller = controller_for(exp, config)
    return exp, controller, [controller._build_variant_njr(v, exp) for v in controller.learning_state.plan]


# -- reproduction guard: the confirmed defect ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", EXACT)
def test_enabled_global_positive_reaches_exact_profile_arm(tmp_path, target):
    _, (sdxl, other) = arms_for(tmp_path, [SDXL, target])
    # SDXL keeps executor ownership: the frozen text and enable flag stay in its executor policy.
    assert sdxl["effective_config"]["global_positive_prompt"] == GLOBAL
    assert sdxl["effective_config"]["pipeline"]["apply_global_positive_txt2img"] is True
    assert sdxl["executor_base_positive_prompt"] == BASE
    assert sdxl["global_positive"]["mode"] == "executor_applied"
    assert sdxl["effective_global_positive_prompt"] == ""
    # The exact profile clears executor-global terms, so the compiler carries the contribution - once.
    assert other["executor_base_positive_prompt"] == f"{GLOBAL}, {BASE}"
    assert other["effective_config"]["txt2img"]["prompt"] == other["executor_base_positive_prompt"]
    assert other["effective_config"]["prompt"] == other["executor_base_positive_prompt"]
    assert other["effective_config"]["global_positive_prompt"] == ""
    assert other["effective_config"]["pipeline"]["apply_global_positive_txt2img"] is False
    assert other["global_positive"] == {
        "contract": "learning_model_comparison_global_positive/1",
        "mode": "compiler_composed",
        "requested": True,
    }
    assert other["effective_global_positive_prompt"] == GLOBAL
    assert len(operations(other, "global_positive_composed")) == 1
    assert other["prompt_adaptation"]["changed"] is True
    assert other["adapted_positive_prompt"] == BASE  # the structured projection never contains the global


@pytest.mark.parametrize("models", [[SDXL, ZIMAGE], [ZIMAGE, SDXL], [KLEIN, ZIMAGE], [ZIMAGE, KLEIN, SDXL], [SDXL, KLEIN, ZIMAGE]])
def test_every_candidate_order_carries_the_shared_terms_once(tmp_path, models):
    config = global_baseline()
    original = copy.deepcopy(config)
    snapshot, arms = arms_for(tmp_path, models, config=config)
    assert config == original  # the shared baseline is never normalized
    assert snapshot["model_comparison"]["global_positive"] == {
        "contract": "learning_model_comparison_global_positive/1",
        "enabled": True,
        "text": GLOBAL,
    }
    for arm in arms:
        executor_owned = arm["model_policy_context"]["family"] == "sdxl"
        assert arm["global_positive"]["mode"] == ("executor_applied" if executor_owned else "compiler_composed")
        terms = arm["effective_config"]["global_positive_prompt"]
        flag = arm["effective_config"]["pipeline"]["apply_global_positive_txt2img"]
        assert (terms, flag) == ((GLOBAL, True) if executor_owned else ("", False))
        assert arm["executor_base_positive_prompt"] == (BASE if executor_owned else f"{GLOBAL}, {BASE}")
        assert frozen_arm(snapshot, arm["selected_model"] if False else models[arm["candidate_index"]]) == arm
    # Arms are independent: nothing leaked between their configurations.
    assert len({id(arm["effective_config"]) for arm in arms}) == len(arms)


@pytest.mark.parametrize(
    ("enabled", "text", "requested"),
    [(False, GLOBAL, False), (True, "", False), (False, "", False)],
    ids=["disabled-nonempty", "enabled-empty", "none"],
)
@pytest.mark.parametrize("models", [[SDXL, ZIMAGE], [SDXL, KLEIN]])
def test_unrequested_global_positive_is_never_applied(tmp_path, models, enabled, text, requested):
    snapshot, arms = arms_for(tmp_path, models, config=global_baseline(enabled=enabled, text=text))
    assert snapshot["model_comparison"]["global_positive"]["enabled"] is enabled
    for arm in arms:
        assert arm["global_positive"]["mode"] == "not_requested"
        assert arm["global_positive"]["requested"] is requested
        assert arm["effective_global_positive_prompt"] == ""
        assert arm["executor_base_positive_prompt"] == BASE
        config = arm["effective_config"]
        # Whatever the flag says, the executor has no terms to apply for a request that was never made.
        applicable = config["global_positive_prompt"] if config["pipeline"]["apply_global_positive_txt2img"] else ""
        assert applicable == ""
        assert not operations(arm, "global_positive_composed")
    # Stored terms are retained for the executor-owned arm but are not enabled; exact profiles hold none.
    sdxl, other = arms
    assert sdxl["effective_config"]["global_positive_prompt"] == text
    assert other["effective_config"]["global_positive_prompt"] == ""
    if text:
        # Same content-free evidence as the generic PromptPack path for a target that cannot hold the terms.
        assert operations(other, "global_positive_not_applied")[0]["details"] == {"enabled": False}
        assert not operations(sdxl, "global_positive_not_applied")


def test_ordinary_sdxl_only_study_is_unchanged_by_parity(tmp_path):
    snapshot, arms = arms_for(tmp_path, [SDXL, "peer.safetensors"])
    for arm in arms:
        assert arm["global_positive"]["mode"] == "executor_applied"
        assert arm["executor_base_positive_prompt"] == BASE
        assert not arm["prompt_adaptation"]["changed"]
        assert arm["effective_config"]["global_negative_prompt"] == "global negative"
        assert arm["adapted_negative_prompt"] == "global negative, bad"
        assert arm["executor_base_negative_prompt"] == "bad"
        assert not operations(arm, "global_positive_composed")


# -- adaptation: weighted syntax and BREAK, content-free evidence -------------------------------------------------------


@pytest.mark.parametrize("target", EXACT)
def test_weighted_and_break_global_terms_are_adapted_once_with_content_free_evidence(tmp_path, target):
    snapshot, (sdxl, other) = arms_for(tmp_path, [SDXL, target], config=global_baseline(text=WEIGHTED_GLOBAL))
    # The executor-owned arm keeps the operator's text verbatim; the compile arm receives the dialect-adapted form.
    assert sdxl["effective_config"]["global_positive_prompt"] == WEIGHTED_GLOBAL
    assert other["effective_global_positive_prompt"] == "studio lighting\n\nfilm grain"
    assert other["executor_base_positive_prompt"] == f"studio lighting\n\nfilm grain, {BASE}"
    flattened = operations(other, "weighted_attention_flattened")
    normalized = operations(other, "break_separator_normalized")
    assert [op["details"] for op in flattened] == [{"count": 1}]
    assert [op["details"] for op in normalized] == [{"count": 1}]
    assert len(operations(other, "global_positive_composed")) == 1
    evidence = json.dumps(other["prompt_adaptation"])
    assert "studio" not in evidence and "film" not in evidence
    assert not operations(sdxl, "weighted_attention_flattened")
    frozen_arm(snapshot, target)


# -- real executor boundary: exactly once --------------------------------------------------------------------------------


def test_fake_backend_payload_receives_global_positive_exactly_once_for_every_candidate(tmp_path, monkeypatch):
    _, _, records = records_for(tmp_path, [SDXL, KLEIN, ZIMAGE], global_baseline())
    prompts = []
    for record in records:
        client = zimage_client() if record.base_model == ZIMAGE else None
        payload = dispatch(record, tmp_path, monkeypatch, client=client)
        assert payload["prompt"].count(GLOBAL) == 1
        prompts.append(payload["prompt"])
    # Equivalent authored positive intent across SDXL, Klein and Z-Image.
    assert prompts == [f"{GLOBAL}, {BASE}"] * 3
    # Only the executor-owned arm lets the executor apply it; the others carry it in the NJR positive prompt.
    assert [r.positive_prompt for r in records] == [BASE, f"{GLOBAL}, {BASE}", f"{GLOBAL}, {BASE}"]
    assert [r.config["pipeline"]["apply_global_positive_txt2img"] for r in records] == [True, False, False]


def test_fake_backend_payload_never_receives_a_disabled_stored_global_positive(tmp_path, monkeypatch):
    _, _, records = records_for(tmp_path, [SDXL, KLEIN, ZIMAGE], global_baseline(enabled=False))
    for record in records:
        client = zimage_client() if record.base_model == ZIMAGE else None
        assert dispatch(record, tmp_path, monkeypatch, client=client)["prompt"] == BASE


# -- Preview/Run agreement, freeze -> save -> restore -> Run -------------------------------------------------------------


def test_preview_run_equivalence_after_live_inputs_change(tmp_path, monkeypatch):
    models = [SDXL, ZIMAGE, KLEIN]
    exp = study(tmp_path, models=models, text=PROSE)
    config = global_baseline()
    controller = controller_for(exp, config)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    preview_text = preview_summary(snapshot)

    # Save -> restore through the real experiment/resume serializers, then mutate every live input.
    restored = LearningExperiment.from_dict(exp.to_dict())
    assert restored.execution_snapshot_json == exp.execution_snapshot_json
    resumed = LearningController(learning_state=LearningState())
    assert resumed.restore_resume_state(controller.export_resume_state())
    (tmp_path / "pack.json").write_text("changed after Preview", encoding="utf-8")
    config.update(global_positive_prompt="LIVE CHANGE")
    config["pipeline"].update(apply_global_positive_txt2img=False)
    for target in (
        "src.learning.experiment_freeze.load_prompt_pack_document",
        "src.pipeline.resolution_layer.adapt_pack_intent",
        "src.pipeline.resolution_layer.adapt_structured_prompt",
        "src.prompting.prompt_adaptation.adapt_structured_prompt",
    ):
        monkeypatch.setattr(target, lambda *a, **kw: pytest.fail("Run reinterpreted the frozen study"))
    resumed._get_baseline_config = lambda: pytest.fail("Run read mutable GUI/global settings")
    resumed._learning_policy_resolver = lambda _: pytest.fail("Run resolved a live target")
    resumed.pipeline_controller = object()
    submit = Mock()
    resumed.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    resumed.run_plan()

    assert submit.call_count == 1
    records = submit.call_args.args[0]
    assert preview_summary(thaw_snapshot(restored.execution_snapshot_json)) == preview_text
    for record, arm in zip(records, snapshot["model_comparison"]["arms"], strict=True):
        assert record.positive_prompt == arm["executor_base_positive_prompt"] == record.config["prompt"]
        assert record.config["global_positive_prompt"] == arm["effective_config"]["global_positive_prompt"]
        metadata = record.provenance.to_dict()["metadata"]
        assert metadata["model_comparison"] == arm
        assert metadata["model_comparison"]["global_positive"] == arm["global_positive"]
        assert metadata["prompt_adaptation"] == arm["prompt_adaptation"]
    assert [r.positive_prompt for r in records] == [BASE, f"{GLOBAL}, {BASE}", f"{GLOBAL}, {BASE}"]


def test_atomic_admission_through_the_job_service_boundary(tmp_path):
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend

    exp = study(tmp_path, models=[SDXL, ZIMAGE], text=PROSE)
    controller = controller_for(exp, global_baseline())
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(controller.learning_state, service)
    controller.run_plan()
    assert service.submit_njrs.call_count == 1
    records = service.submit_njrs.call_args.args[0]
    backend = ForgeWebUIImageBackend()
    for record in records:
        backend.validate_njr_intent(record, ["txt2img"])
    assert [r.positive_prompt for r in records] == [BASE, f"{GLOBAL}, {BASE}"]
    assert records[1].config["global_positive_prompt"] == ""


def test_rating_provenance_carries_the_global_positive_representation(tmp_path):
    from src.learning.learning_record import LearningRecordWriter

    exp = study(tmp_path, models=[SDXL, KLEIN], text=PROSE)
    controller = controller_for(exp, global_baseline())
    controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    for index, variant in enumerate(controller.learning_state.plan):
        controller._build_variant_njr(variant, exp)
        variant.image_refs = [f"image-{index}.png"]
        controller.record_rating(variant.image_refs[0], 4)
    rows = [json.loads(line)["metadata"] for line in (tmp_path / "ratings.jsonl").read_text().splitlines()]
    assert [row["model_comparison"]["global_positive"]["mode"] for row in rows] == [
        "executor_applied",
        "compiler_composed",
    ]
    assert rows[1]["model_comparison"]["effective_global_positive_prompt"] == GLOBAL
    assert all(row["prompt_semantics"] == "executor_base_before_globals_and_optimizer" for row in rows)


# -- Preview summary --------------------------------------------------------------------------------------------------


def test_preview_summary_distinguishes_global_positive_ownership_without_content(tmp_path):
    snapshot, _ = arms_for(tmp_path, [SDXL, KLEIN, ZIMAGE])
    summary = preview_summary(snapshot)
    rows = summary.splitlines()[1:]
    assert "Global positive: applied at execution." in rows[0]
    assert "Global positive: composed into the prompt." in rows[1]
    assert "Global positive: composed into the prompt." in rows[2]
    assert GLOBAL not in summary and "pack.json" not in summary
    disabled, _ = arms_for(tmp_path / "d", [SDXL, KLEIN], config=global_baseline(enabled=False)) if (tmp_path / "d").mkdir() is None else (None, None)
    assert preview_summary(disabled).count("Global positive: disabled (not applied).") == 2
    none, _ = arms_for(tmp_path / "e", [SDXL, KLEIN], config=global_baseline(text="")) if (tmp_path / "e").mkdir() is None else (None, None)
    assert "Global positive" not in preview_summary(none)


# -- refusal at Build Preview --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["rim light <lora:glow:0.5>", "soft [light] glow", "<embedding:thing>"])
def test_unsupported_inline_global_terms_refuse_at_preview(tmp_path, text):
    with pytest.raises(ValueError, match=r"arm 2.*No arm was queued"):
        build(tmp_path, models=[SDXL, ZIMAGE], text=PROSE, config=global_baseline(text=text))


def test_inline_adapter_token_in_global_terms_is_admitted_like_authored_prose_for_klein(tmp_path):
    """Preview does not pre-parse inline tokens for Klein; the exact profile's LoRA authority decides at admission."""
    from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend

    def klein_record(base, text, config):
        _, snapshot = build(tmp_path / base, models=[SDXL, KLEIN], text=text, config=config)
        return materialize_njr(
            snapshot,
            SimpleNamespace(param_value=KLEIN, executed_config=None),
            metadata_factory=lambda cfg: {},
            output_dir="output",
            filename_template="{seed}",
        )

    for name in ("global", "prose"):
        (tmp_path / name).mkdir()
    via_global = klein_record("global", PROSE, global_baseline(text="rim light <lora:glow:0.5>"))
    via_prose = klein_record("prose", "a red dress <lora:glow:0.5> in [[place]]", global_baseline(enabled=False))
    verdicts = []
    for record in (via_global, via_prose):
        assert "<lora:glow:0.5>" in record.positive_prompt
        outcome = []
        for resolver in (
            None,
            lambda n: KleinLoraDecision(n, KleinLoraStatus.COMPATIBLE, "fixture"),
            lambda n: KleinLoraDecision(n, KleinLoraStatus.INCOMPATIBLE, "fixture"),
        ):
            backend = ForgeWebUIImageBackend(**({"lora_resolver": resolver} if resolver else {}))
            try:
                backend.validate_njr_intent(record, ["txt2img"])
                outcome.append("accepted")
            except ValueError:
                outcome.append("refused")
        verdicts.append(outcome)
    # An unverified or incompatible LoRA is refused at admission and only an explicitly compatible one is accepted -
    # identically whether the token arrived through the global terms or the authored prose.
    assert verdicts[0] == verdicts[1] == ["refused", "accepted", "refused"]


def test_unsupported_inline_global_terms_do_not_refuse_an_executor_owned_only_study(tmp_path):
    arms_for(tmp_path, [SDXL, "peer.safetensors"], config=global_baseline(text="rim light <lora:glow:0.5>"))


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda c: c["txt2img"].update(width=768, height=1024), "geometry"),
        (lambda c: c["txt2img"].update(batch_size=2), "batch_size"),
        (lambda c: c["backend_options"]["image"].update(backend_id="a1111_webui"), "backend"),
        (lambda c: c["pipeline"].update(img2img_enabled=True), "stage chain"),
    ],
)
def test_global_positive_never_relaxes_exact_profile_restrictions(tmp_path, change, match):
    config = global_baseline()
    change(config)
    with pytest.raises(ValueError, match=match):
        build(tmp_path, models=[SDXL, ZIMAGE], text=PROSE, config=config)


def test_unknown_target_still_refuses_with_global_positive(tmp_path):
    with pytest.raises(ValueError, match="unavailable or conflicting"):
        build(tmp_path, models=[SDXL, "unknown"], text=PROSE, config=global_baseline())


def test_global_positive_that_adapts_to_nothing_is_refused_for_the_arm(tmp_path):
    with pytest.raises(ValueError, match=r"arm 2.*global positive"):
        build(tmp_path, models=[SDXL, ZIMAGE], text=PROSE, config=global_baseline(text="BREAK"))


# -- frozen integrity -------------------------------------------------------------------------------------------------


def _set_prompts(arm, text):
    arm["executor_base_positive_prompt"] = text
    for container in (arm["effective_config"], arm["effective_config"]["txt2img"]):
        container["prompt"] = text


def _flags_on(arm):
    arm["effective_config"]["pipeline"]["apply_global_positive_txt2img"] = True
    arm["effective_config"]["global_positive_prompt"] = GLOBAL
    arm["executor_global_prompt_policy"]["pipeline"]["apply_global_positive_txt2img"] = True
    arm["executor_global_prompt_policy"]["global_positive_prompt"] = GLOBAL


def _drop_composed_operation(arm):
    arm["prompt_adaptation"]["operations"] = [
        op for op in arm["prompt_adaptation"]["operations"] if op["code"] != "global_positive_composed"
    ]


def _duplicate_composed_operation(arm):
    arm["prompt_adaptation"]["operations"].append(operations(arm, "global_positive_composed")[0])


def _set(key, value):
    def apply(arm):
        arm[key] = value

    return apply


def _block(**changes):
    def apply(arm):
        arm["global_positive"].update(changes)

    return apply


COMPOSED_TAMPERS = {
    "prompt_without_composition": lambda a: _set_prompts(a, BASE),
    "prompt_forged": lambda a: _set_prompts(a, f"forged, {BASE}"),
    "prompt_doubled": lambda a: _set_prompts(a, f"{GLOBAL}, {GLOBAL}, {BASE}"),
    "contribution_changed": _set("effective_global_positive_prompt", "other terms"),
    "contribution_removed": _set("effective_global_positive_prompt", ""),
    "mode_executor": _block(mode="executor_applied"),
    "mode_not_requested": _block(mode="not_requested"),
    "mode_unknown": _block(mode="composed"),
    "requested_flipped": _block(requested=False),
    "contract_changed": _block(contract="other/1"),
    "block_field_added": _block(extra=True),
    "block_removed": lambda a: a.pop("global_positive"),
    "contribution_field_removed": lambda a: a.pop("effective_global_positive_prompt"),
    "executor_flags_double_application": _flags_on,
    "operation_removed": _drop_composed_operation,
    "operation_duplicated": _duplicate_composed_operation,
    "changed_flag_cleared": lambda a: a["prompt_adaptation"].update(changed=False),
}


@pytest.mark.parametrize("target", EXACT)
@pytest.mark.parametrize("tamper", sorted(COMPOSED_TAMPERS))
def test_tampered_composed_arm_is_rejected_even_when_resealed(tmp_path, target, tamper):
    snapshot, arms = arms_for(tmp_path, [SDXL, target])
    frozen_arm(snapshot, target)
    arm = arms[1]
    COMPOSED_TAMPERS[tamper](arm)
    with pytest.raises(ValueError):
        frozen_arm(snapshot, target)  # stale digest
    reseal(arm)
    with pytest.raises(ValueError):
        frozen_arm(snapshot, target)
    with pytest.raises(ValueError):
        verify_arms_admissible(snapshot)


EXECUTOR_TAMPERS = {
    "composed_on_top_of_executor_flag": lambda a: (
        _block(mode="compiler_composed")(a),
        _set("effective_global_positive_prompt", GLOBAL)(a),
        _set_prompts(a, f"{GLOBAL}, {BASE}"),
    ),
    "executor_flag_turned_off": lambda a: (
        a["effective_config"]["pipeline"].update(apply_global_positive_txt2img=False),
        a["executor_global_prompt_policy"]["pipeline"].update(apply_global_positive_txt2img=False),
    ),
    "executor_text_changed": lambda a: (
        a["effective_config"].update(global_positive_prompt="other"),
        a["executor_global_prompt_policy"].update(global_positive_prompt="other"),
    ),
    "prompt_prepended_by_hand": lambda a: _set_prompts(a, f"{GLOBAL}, {BASE}"),
    "mode_not_requested": _block(mode="not_requested"),
    "contribution_added": _set("effective_global_positive_prompt", GLOBAL),
}


@pytest.mark.parametrize("tamper", sorted(EXECUTOR_TAMPERS))
def test_tampered_executor_owned_arm_is_rejected_even_when_resealed(tmp_path, tamper):
    snapshot, arms = arms_for(tmp_path, [SDXL, "peer.safetensors"])
    frozen_arm(snapshot, SDXL)
    EXECUTOR_TAMPERS[tamper](arms[0])
    reseal(arms[0])
    with pytest.raises(ValueError):
        frozen_arm(snapshot, SDXL)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda g: g.update(text="different terms"),
        lambda g: g.update(enabled=False),
        lambda g: g.update(contract="other/1"),
        lambda g: g.update(text=f" {GLOBAL} "),
        lambda g: g.pop("text"),
    ],
    ids=["text", "enabled", "contract", "unstripped", "missing"],
)
def test_tampered_shared_global_positive_record_is_rejected(tmp_path, tamper):
    snapshot, _ = arms_for(tmp_path, [SDXL, KLEIN])
    tamper(snapshot["model_comparison"]["global_positive"])
    with pytest.raises(ValueError):
        frozen_arm(snapshot, SDXL)


def test_new_study_cannot_become_legacy_by_removing_its_marker(tmp_path):
    snapshot, _ = arms_for(tmp_path, [SDXL, KLEIN])
    del snapshot["model_comparison"]["global_positive"]
    with pytest.raises(ValueError):
        frozen_arm(snapshot, KLEIN)


def test_study_without_global_positive_still_validates_every_arm_requirement(tmp_path):
    # An "enabled but never requested" style study (no stored terms) is a *new* study: its arms still carry the block.
    snapshot, arms = arms_for(tmp_path, [SDXL, KLEIN], config=global_baseline(text=""))
    del arms[0]["global_positive"]
    reseal(arms[0])
    with pytest.raises(ValueError):
        frozen_arm(snapshot, SDXL)


# -- previously frozen studies keep their original meaning -----------------------------------------------------------------


@pytest.fixture(scope="module")
def legacy():
    return json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8"))


def test_legacy_fixture_was_frozen_without_parity(legacy):
    study = legacy["sdxl_klein_zimage_enabled"]["model_comparison"]
    assert "global_positive" not in study
    assert all("global_positive" not in arm for arm in study["arms"])


@pytest.mark.parametrize("name", ["sdxl_klein_zimage_enabled", "sdxl_klein_disabled"])
def test_legacy_snapshots_retain_prior_semantics(legacy, name):
    snapshot = copy.deepcopy(legacy[name])
    verify_arms_admissible(snapshot)  # every frozen arm still materializes through the exact Run boundary
    summary = preview_summary(snapshot)
    assert "Global positive" not in summary
    for model in snapshot["variant_values"]:
        arm = frozen_arm(snapshot, model)
        # Prior meaning: an exact-profile arm froze without the enabled global positive; it is neither reinterpreted
        # nor silently upgraded to include it.
        assert arm["executor_base_positive_prompt"] == BASE
        record = materialize_njr(
            snapshot,
            SimpleNamespace(param_value=model, executed_config=None),
            metadata_factory=lambda config: {},
            output_dir="output",
            filename_template="{seed}",
        )
        assert record.positive_prompt == BASE
        assert "global_positive" not in record.provenance.metadata["model_comparison"]


def test_legacy_snapshot_cannot_be_partially_upgraded(legacy):
    snapshot = copy.deepcopy(legacy["sdxl_klein_zimage_enabled"])
    study_record = snapshot["model_comparison"]
    klein = study_record["arms"][1]
    klein["global_positive"] = {
        "contract": "learning_model_comparison_global_positive/1",
        "mode": "not_requested",
        "requested": False,
    }
    reseal(klein)
    with pytest.raises(ValueError):
        frozen_arm(snapshot, KLEIN)
    snapshot = copy.deepcopy(legacy["sdxl_klein_zimage_enabled"])
    snapshot["model_comparison"]["global_positive"] = {
        "contract": "learning_model_comparison_global_positive/1",
        "enabled": True,
        "text": GLOBAL,
    }
    with pytest.raises(ValueError):
        frozen_arm(snapshot, SDXL)


def test_legacy_experiment_round_trips_and_runs_with_prior_prompts(legacy, tmp_path):
    snapshot = copy.deepcopy(legacy["sdxl_klein_zimage_enabled"])
    exp = LearningExperiment(
        name="comparison",
        experiment_id=snapshot["experiment_id"],
        stage="txt2img",
        images_per_value=1,
        metadata={"study_type": "model_comparison"},
        execution_snapshot_json=freeze_snapshot(snapshot),
    )
    restored = LearningExperiment.from_dict(exp.to_dict())
    assert restored.execution_snapshot_json == exp.execution_snapshot_json
    verify_arms_admissible(thaw_snapshot(restored.execution_snapshot_json))
