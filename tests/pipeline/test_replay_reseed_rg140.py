"""RG-140 slice 2: "more like this" re-runs a whole recipe as a Replay with only the seed changed."""

from __future__ import annotations

import pytest

from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent, reseed_refusals
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

N5_BATCH = {
    "schema": "stablenew.batch.v1",
    "batch_id": "5b0c4f8e-2a1d-4e3b-9c7a-1f2e3d4c5b6a",
    "name": "portraits x 2 models",
    "cell": {"pack_name": "portraits", "model": "juggernautXL.safetensors"},
}


def _recipe(**overrides):
    return make_pipeline_njr(
        job_id="parent",
        stage_chain=(
            make_stage_config("txt2img"),
            make_stage_config("adetailer"),
            make_stage_config("upscale"),
        ),
        config={"seed": 42, "txt2img": {"seed": 42, "steps": 30}, "adetailer": {"steps": 12}},
        extra_metadata={"batch": dict(N5_BATCH)},
        seed=42,
        **overrides,
    )


def test_a_reseed_keeps_the_whole_recipe_and_changes_only_the_seed() -> None:
    parent = _recipe()
    assert reseed_refusals(parent) == ()

    child = compile_replay_intent(
        ReplayIntent(parent, parent_artifact_id="sha256:" + "a" * 64, seed=1234),
        id_fn=lambda: "child-1",
    )

    assert child.job_id == "child-1" and child.seed == 1234
    assert child.stage_chain_labels == ["txt2img", "adetailer", "upscale"]
    config = child.config
    assert (config["seed"], config["txt2img"]["seed"], config["txt2img"]["steps"]) == (
        1234,
        1234,
        30,
    )
    assert config["adetailer"] == parent.config["adetailer"]
    assert child.positive_prompt == parent.positive_prompt
    assert child.source.parent_job_id == "parent"
    assert child.source.parent_artifact_id == "sha256:" + "a" * 64
    metadata = child.provenance.metadata
    assert metadata["reseed"] == {"parent_seed": 42}
    # A new submission, not another member of the parent's N5 batch: the batch is kept inert, as for any Replay.
    assert "batch" not in metadata and metadata["replay_origin"]["batch"] == N5_BATCH
    # The persisted parent is never changed.
    assert parent.seed == 42 and parent.config["seed"] == 42


def test_a_replay_without_a_seed_is_unchanged() -> None:
    parent = _recipe()

    replay = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "replay-2")

    assert replay.seed == 42 and "reseed" not in replay.provenance.metadata
    assert replay.to_dict()["workload"] == parent.to_dict()["workload"]


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"stage_chain": (make_stage_config("img2img"),)}, "starts with text-to-image"),
        ({"images_per_prompt": 2}, "Multi-image"),
    ],
)
def test_what_cannot_be_reseeded_is_named(overrides, reason) -> None:
    record = make_pipeline_njr(**overrides)

    assert any(reason in text for text in reseed_refusals(record))
    with pytest.raises(ValueError):
        compile_replay_intent(ReplayIntent(record, seed=7))


@pytest.mark.parametrize("seed", [-1, 2**32, True])
def test_a_reseed_needs_a_concrete_seed(seed) -> None:
    with pytest.raises(ValueError):
        compile_replay_intent(ReplayIntent(_recipe(), seed=seed))
