"""Unit tests for the single NJR assembly boundary (P4-2B).

Policy states: a RAW draft runs each shared step once and in the fixed order, an EFFECTIVE draft runs none, a FROZEN
draft is never transformed and an altered value is refused. Derivation: a new identity with parent lineage, the same
contract the replay and variation compilers had before they moved onto the core.
"""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.pipeline import njr_compiler
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.job_models_v2 import (
    ImageWorkloadSpec,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    TrainingWorkloadSpec,
    WorkloadKind,
)
from src.pipeline.njr_compiler import (
    CompileCheck,
    FrozenExpectation,
    NjrDerivation,
    NjrDraft,
    PolicyState,
    RawImagePlan,
    compile_njr,
    derive_njr,
    history_lineage,
    mint_job_id,
    reprocess_source_kind,
)
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent

REPO = Path(__file__).resolve().parents[2]
STEPS = (
    "prepare_effective_config",
    "apply_model_compile_policy",
    "compile_adetailer",
    "normalize_image_backend_options",
    "canonicalize_intent_config",
)


def _image_draft(state: PolicyState, **overrides: Any) -> NjrDraft:
    fields: dict[str, Any] = {
        "job_id": "job-1",
        "workload_kind": WorkloadKind.IMAGE,
        "source": SourceDescriptor(kind=SourceKind.CLI, display_name="unit"),
        "workload": ImageWorkloadSpec(
            positive_prompt="a lighthouse",
            negative_prompt="blurry",
            config={
                "txt2img": {"model": "model-a.safetensors", "steps": 12},
                "backend_options": {},
            },
            intent_config={"source": "unit"},
        ),
        "stages": (StageConfig(stage_type="txt2img", enabled=True, steps=12),),
        "output_plan": OutputPlan(),
        "provenance": NJRProvenance(seed=7, metadata={"origin": "unit"}),
        "policy_state": state,
    }
    fields.update(overrides)
    return NjrDraft(**fields)


@pytest.fixture
def step_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wrap every shared step the core can run so the test sees which ran, how often and in what order."""

    calls: list[str] = []
    for name in STEPS:
        original = getattr(njr_compiler, name)

        def wrapped(*args: Any, _name: str = name, _original: Any = original, **kwargs: Any) -> Any:
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(njr_compiler, name, wrapped)
    return calls


def _stages_from_config(config: Any) -> tuple[StageConfig, ...]:
    return (
        StageConfig(stage_type="txt2img", enabled=True, model=config["txt2img"]["model"], steps=30),
    )


RAW_PLAN = RawImagePlan(
    stages_for=_stages_from_config, model_name_for=lambda config: config["txt2img"]["model"]
)


def test_a_raw_draft_runs_each_shared_step_once_in_the_fixed_order(step_calls: list[str]) -> None:
    record = compile_njr(_image_draft(PolicyState.RAW, raw_plan=RAW_PLAN))

    assert step_calls == list(STEPS)
    assert (
        record.stages[0].steps == 30
    )  # stages come from the planner's rule over the effective configuration
    assert record.stages[0].model == "model-a.safetensors"
    assert record.provenance.metadata["origin"] == "unit"


def test_an_effective_draft_runs_no_shared_step_and_is_assembled_as_given(
    step_calls: list[str],
) -> None:
    draft = _image_draft(PolicyState.EFFECTIVE)

    record = compile_njr(draft)

    assert step_calls == []
    assert isinstance(record, NormalizedJobRecord)
    assert (record.job_id, record.source, record.workload, record.stages) == (
        draft.job_id,
        draft.source,
        draft.workload,
        draft.stages,
    )
    assert record.provenance == draft.provenance


def test_a_frozen_draft_is_not_transformed(step_calls: list[str]) -> None:
    draft = _image_draft(
        PolicyState.FROZEN,
        frozen=FrozenExpectation(
            values={"positive_prompt": "a lighthouse", "workload.config": draft_config()},
            message="does not match the frozen snapshot",
        ),
    )

    record = compile_njr(draft)

    assert step_calls == []
    assert record.workload == draft.workload


def draft_config() -> dict[str, Any]:
    return {"txt2img": {"model": "model-a.safetensors", "steps": 12}, "backend_options": {}}


def test_a_frozen_draft_with_an_altered_value_is_refused() -> None:
    draft = _image_draft(
        PolicyState.FROZEN,
        frozen=FrozenExpectation(
            values={"positive_prompt": "a different prompt"},
            message="does not match the frozen snapshot",
        ),
    )

    with pytest.raises(ValueError, match="^does not match the frozen snapshot$"):
        compile_njr(draft)


def test_a_frozen_draft_without_its_expectation_is_refused() -> None:
    with pytest.raises(ValueError, match="frozen expectation"):
        compile_njr(_image_draft(PolicyState.FROZEN))


def test_a_raw_draft_needs_an_image_workload_and_a_plan() -> None:
    with pytest.raises(ValueError, match="raw_plan"):
        compile_njr(_image_draft(PolicyState.RAW))
    training = NjrDraft(
        job_id="train-1",
        workload_kind=WorkloadKind.TRAINING,
        source=SourceDescriptor(kind=SourceKind.TRAINING),
        workload=TrainingWorkloadSpec(positive_prompt="Train LoRA", negative_prompt=""),
        stages=(StageConfig(stage_type="train_lora", enabled=True),),
        output_plan=OutputPlan(),
        provenance=NJRProvenance(),
        policy_state=PolicyState.RAW,
        raw_plan=RAW_PLAN,
    )
    with pytest.raises(ValueError, match="image workload"):
        compile_njr(training)


def test_declared_checks_run_in_the_declared_order_on_the_constructed_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[CompileCheck, str]] = []
    for check in CompileCheck:
        monkeypatch.setitem(
            njr_compiler._CHECKS,
            check,
            lambda record, _check=check: seen.append((_check, record.job_id)),
        )

    compile_njr(
        _image_draft(
            PolicyState.EFFECTIVE, checks=(CompileCheck.OPERATION, CompileCheck.PROFILE_NJR)
        )
    )

    assert seen == [(CompileCheck.OPERATION, "job-1"), (CompileCheck.PROFILE_NJR, "job-1")]


def test_a_check_refusal_propagates_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    class Refused(Exception):
        pass

    def refuse(record: Any) -> None:
        raise Refused("the exact text")

    monkeypatch.setitem(njr_compiler._CHECKS, CompileCheck.RETIRED, refuse)

    with pytest.raises(Refused, match="^the exact text$"):
        compile_njr(_image_draft(PolicyState.EFFECTIVE, checks=(CompileCheck.RETIRED,)))


def test_mint_job_id_uses_the_injected_identity_or_a_random_hex() -> None:
    assert mint_job_id(lambda: 42) == "42"
    generated = mint_job_id()
    assert re.fullmatch(r"[0-9a-f]{32}", generated)


@pytest.mark.parametrize(
    ("source", "is_video", "expected"),
    [
        ("reprocess", False, SourceKind.REPROCESS),
        ("something-new", False, SourceKind.REPROCESS),
        ("image_edit", False, SourceKind.IMAGE_EDIT),
        ("Learning", False, SourceKind.LEARNING),
        ("history", False, SourceKind.HISTORY_REPLAY),
        ("HISTORY_REPLAY", False, SourceKind.HISTORY_REPLAY),
        ("video", False, SourceKind.VIDEO_WORKFLOW),
        ("video_workflow", False, SourceKind.VIDEO_WORKFLOW),
        ("reprocess", True, SourceKind.VIDEO_WORKFLOW),
        ("learning", True, SourceKind.VIDEO_WORKFLOW),
        ("image_edit", True, SourceKind.VIDEO_WORKFLOW),
    ],
)
def test_reprocess_source_kind_keeps_the_alias_table_and_lets_a_video_stage_win(
    source: str, is_video: bool, expected: SourceKind
) -> None:
    assert reprocess_source_kind(source, is_video=is_video) is expected


def test_the_reprocess_builder_assembles_through_the_core_with_no_construction_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.pipeline.reprocess_builder import ReprocessJobBuilder

    image = tmp_path / "source.png"
    image.write_bytes(b"x")
    drafts: list[NjrDraft] = []
    real = njr_compiler.compile_njr

    def spy(draft: NjrDraft) -> NormalizedJobRecord:
        drafts.append(draft)
        return real(draft)

    monkeypatch.setattr("src.pipeline.reprocess_builder.compile_njr", spy)

    record = ReprocessJobBuilder(id_fn=lambda: "reprocess-1").build_reprocess_job(
        input_image_paths=[str(image)], stages=["upscale"], config={"upscale": {}}
    )

    assert record.job_id == "reprocess-1"
    assert [(d.policy_state, d.checks) for d in drafts] == [(PolicyState.EFFECTIVE, ())]


# --- derivation -----------------------------------------------------------------------------------------------------


def _parent() -> NormalizedJobRecord:
    return build_cli_njr(
        prompt="a lighthouse",
        config={"txt2img": {"model": "model-a.safetensors", "steps": 12, "seed": 5}},
        batch_size=1,
        run_name="parent-job",
    )


def test_history_lineage_records_the_parent_and_its_original_source_kind() -> None:
    parent = _parent()

    lineage = history_lineage(parent, parent_artifact_id="artifact-9", metadata={"extra": 1})

    assert lineage.kind is SourceKind.HISTORY_REPLAY
    assert lineage.parent_job_id == "parent-job"
    assert lineage.parent_artifact_id == "artifact-9"
    assert lineage.display_name == parent.source.display_name == "parent-job"
    assert list(lineage.metadata) == ["original_source_kind", "extra"]
    assert lineage.metadata["original_source_kind"] == "cli"


def test_history_lineage_lets_caller_metadata_win_and_can_clear_the_display_name() -> None:
    parent = _parent()

    lineage = history_lineage(
        parent, metadata={"original_source_kind": "prompt_pack"}, display_name=None
    )

    assert lineage.metadata["original_source_kind"] == "prompt_pack"
    assert lineage.display_name is None


def test_derive_njr_assigns_the_new_identity_and_carries_every_omitted_part() -> None:
    parent = _parent()

    child = derive_njr(parent, NjrDerivation(job_id="child-1", source=history_lineage(parent)))

    assert child.job_id == "child-1"
    assert child.source.parent_job_id == parent.job_id
    assert (child.workload, child.stages, child.output_plan, child.provenance) == (
        parent.workload,
        parent.stages,
        parent.output_plan,
        parent.provenance,
    )
    assert parent.job_id == "parent-job"  # the parent is never mutated


def test_derive_njr_without_a_source_re_identifies_and_keeps_the_parent_source() -> None:
    parent = _parent()
    provenance = replace(parent.provenance, metadata={"re_identified": True})

    child = derive_njr(parent, NjrDerivation(job_id="child-2", provenance=provenance))

    assert child.source == parent.source
    assert child.provenance.metadata == {"re_identified": True}


def test_derive_njr_runs_its_checks_on_the_derived_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setitem(
        njr_compiler._CHECKS, CompileCheck.OPERATION, lambda record: seen.append(record.job_id)
    )

    derive_njr(_parent(), NjrDerivation(job_id="child-3", checks=(CompileCheck.OPERATION,)))

    assert seen == ["child-3"]


def test_replay_derivation_matches_the_replay_lineage_contract() -> None:
    parent = _parent()

    replay = compile_replay_intent(
        ReplayIntent(parent, parent_artifact_id="artifact-1"), id_fn=lambda: "replay-1"
    )

    assert replay.job_id == "replay-1"
    assert replay.source.kind is SourceKind.HISTORY_REPLAY
    assert replay.source.parent_job_id == parent.job_id
    assert replay.source.parent_artifact_id == "artifact-1"
    assert replay.source.metadata["original_source_kind"] == "cli"
    assert replay.extra_metadata["replay"] is True
    assert replay.extra_metadata["parent_job_id"] == parent.job_id
    assert replay.workload == parent.workload


def test_replay_run_directives_replace_inherited_ones_on_the_named_stage() -> None:
    parent = _parent()
    stage = replace(parent.stages[0], extra={"sequence_resume": {"old": True}, "keep": 1})
    config = {"txt2img": {"sequence_resume": {"old": True}, "steps": 12}}
    parent = replace(parent, stages=(stage,), workload=replace(parent.workload, config=config))

    replay = compile_replay_intent(
        ReplayIntent(parent, run_directives={"txt2img": {"sequence_replay_of": {"new": True}}}),
        id_fn=lambda: "replay-2",
    )

    assert dict(replay.stages[0].extra) == {"keep": 1, "sequence_replay_of": {"new": True}}
    assert dict(replay.workload.config["txt2img"]) == {
        "steps": 12,
        "sequence_replay_of": {"new": True},
    }


# --- ownership ratchet for the routes moved in P4-2B and P4-2C ----------------------------------------------------------------

MIGRATED = (
    "src/pipeline/cli_njr_builder.py",
    "src/pipeline/training_njr_compiler.py",
    "src/pipeline/replay_njr_compiler.py",
    "src/pipeline/history_variation_compiler.py",
    "src/video/sequence_resume.py",
    "src/pipeline/reprocess_builder.py",
    "src/learning/learning_njr.py",
    "src/learning/ordinary_njr.py",
)
FAMILY_IDENTIFIERS = re.compile(
    r"z_?image|klein|flux|sdxl|sd15|animatediff|qwen|hunyuan|wan2|ltx", re.IGNORECASE
)


@pytest.mark.parametrize("path", MIGRATED)
def test_a_migrated_route_neither_constructs_nor_re_identifies_a_record(path: str) -> None:
    source = (REPO / path).read_text(encoding="utf-8")

    assert "NormalizedJobRecord(" not in source
    re_identifications = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "replace"
        and any(keyword.arg == "job_id" for keyword in node.keywords)
    ]
    assert re_identifications == []


def test_the_core_names_no_model_family() -> None:
    source = (REPO / "src/pipeline/njr_compiler.py").read_text(encoding="utf-8")

    assert FAMILY_IDENTIFIERS.findall(source) == []
