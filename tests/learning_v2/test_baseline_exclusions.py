"""Settings a controlled study refuses are detected, and cleared only in the Learning baseline draft.

Each study's own refusal is the oracle: a fully loaded baseline cleared with ``baseline_exclusions`` must pass the
study's existing check, so the detection here cannot quietly drift from the rule it lets the operator satisfy.
"""

from __future__ import annotations

import copy

import pytest

from src.learning import baseline_exclusions as ex
from src.learning import embedding_experiment, lora_composition, prompt_slot_experiment
from src.learning.prompt_model_matrix import excluded_conditioning, require_matrix_baseline
from src.learning.two_axis_grid import require_plain_txt2img
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.learning_v2.test_model_comparison_140 import SDXL, policy
from tests.learning_v2.test_prompt_model_matrix_710 import preview


def loaded() -> dict:
    """A baseline with every refused feature switched on, in every spelling the executor or a study reads."""
    return {
        "prompt_optimizer": {"enabled": True},
        "style_lora": {"enabled": True, "style_id": "noir"},
        "enable_hr": True,
        "hires_fix": {"enabled": True},
        "use_refiner": True,
        "refiner": {"enabled": True},
        "lora_override": [{"name": "Foo", "weight": 0.5}],
        "aesthetic": {"enabled": True},
        "controlnet_units": [{"enabled": True}],
        "img2img_enabled": True,
        "adetailer": {"enabled": True},
        "upscale": {"enabled": True},
        "pipeline": {"txt2img_enabled": True, "img2img_enabled": True, "upscale_enabled": True},
        "txt2img": {
            "model": SDXL,
            "width": 1024,
            "height": 1024,
            "prompt_optimizer": {"enabled": True},
            "enable_hr": True,
            "use_refiner": True,
            "refiner_enabled": True,
            "refiner_checkpoint": "refiner.safetensors",
            "lora_strengths": [{"name": "Foo", "weight": 0.5}],
            "hypernetwork": "hn",
            "controlnet": {"enabled": True},
        },
    }


def test_a_clean_baseline_has_nothing_to_clear():
    clean = {
        "txt2img": {"model": SDXL, "width": 1024, "height": 1024},
        "pipeline": {"txt2img_enabled": True},
    }
    for study in ex.STUDY_EXCLUSIONS:
        assert ex.present(clean, study) == []
    assert (
        ex.present(loaded(), "controlled_variable") == []
    )  # ordinary sweeps keep their fixed settings


def test_matrix_exclusions_cleared_here_satisfy_the_matrix_refusal():
    config = loaded()
    assert excluded_conditioning(config)
    found = ex.present(config, "prompt_model_matrix")
    assert {ex.PROMPT_OPTIMIZER, ex.HIRES, ex.REFINER, ex.STAGE_LORAS, ex.EXTRA_STAGES} <= set(
        found
    )
    cleared = ex.cleared(config, found)
    assert excluded_conditioning(cleared) == []
    require_matrix_baseline(cleared)
    assert ex.present(cleared, "prompt_model_matrix") == []
    assert config == loaded()  # the input is never mutated
    assert cleared["txt2img"]["model"] == SDXL and cleared["txt2img"]["width"] == 1024


def test_grid_exclusions_cleared_here_satisfy_the_grid_refusal():
    config = loaded()
    with pytest.raises(ValueError):
        require_plain_txt2img(config)
    require_plain_txt2img(ex.cleared(config, ex.present(config, "two_axis_grid")))


@pytest.mark.parametrize(
    "study,check",
    [
        ("lora_composition", lambda p, b: lora_composition.require_target(p, b)),
        ("prompt_slot", lambda p, b: prompt_slot_experiment.require_target(p, b)),
    ],
)
def test_prompt_studies_clear_the_optimizer_and_style_they_refuse(study, check):
    config = loaded()
    with pytest.raises(ValueError):
        check(policy(SDXL), config)
    cleared = ex.cleared(config, ex.present(config, study))
    check(policy(SDXL), cleared)
    # hires/refiner are ordinary fixed settings for these studies (Learning sections 3.11-3.12): kept as authored
    assert cleared["txt2img"]["enable_hr"] is True and cleared["txt2img"]["use_refiner"] is True


def test_embedding_study_clears_the_optimizer_and_style_it_refuses():
    config = loaded()
    found = ex.present(config, "embedding_experiment")
    assert found == [ex.PROMPT_OPTIMIZER, ex.STYLE]
    cleared = ex.cleared(config, found)
    for check_message in ("prompt optimizer", "Style Consistency"):
        try:
            embedding_experiment.require_target(
                policy(SDXL), cleared, embedding_experiment.POSITIVE
            )
        except (
            ValueError
        ) as exc:  # backend/dialect refusals of the fixture policy are not this test's concern
            assert check_message not in str(exc)


def test_labels_name_every_exclusion():
    assert set(ex.LABELS) == {key for keys in ex.STUDY_EXCLUSIONS.values() for key in keys}
    assert ex.describe([ex.PROMPT_OPTIMIZER, ex.HIRES]) == "Prompt optimizer, Hires fix"


def test_the_controller_clears_only_the_learning_draft_and_records_the_edit(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": True}
    bench.pipeline["txt2img"]["enable_hr"] = True
    bench.controller.copy_pipeline_settings("txt2img")
    pipeline_before = copy.deepcopy(bench.pipeline)
    assert bench.controller.baseline_exclusions("prompt_model_matrix") == [
        ex.PROMPT_OPTIMIZER,
        ex.HIRES,
    ]
    assert bench.controller.clear_baseline_exclusions("prompt_model_matrix") == [
        ex.PROMPT_OPTIMIZER,
        ex.HIRES,
    ]
    assert bench.controller.baseline_exclusions("prompt_model_matrix") == []
    assert bench.pipeline == pipeline_before  # the Pipeline is never written
    record = bench.controller.baseline_authoring_record()
    assert "txt2img.excluded:prompt_optimizer" in record["edited"]
    assert bench.controller.clear_baseline_exclusions("prompt_model_matrix") == []
    preview(bench)  # the cleared draft now freezes


def test_matrix_preview_refuses_a_refiner_in_the_txt2img_spelling_the_executor_reads(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["txt2img"].update(use_refiner=True, refiner_checkpoint="refiner.safetensors")
    with pytest.raises(ValueError, match="refiner"):
        preview(bench)


@pytest.mark.parametrize("key", ["use_refiner", "refiner_enabled"])
def test_grid_refuses_a_refiner_in_the_txt2img_section(key):
    with pytest.raises(ValueError, match="refiner"):
        require_plain_txt2img({"txt2img": {key: True}, "pipeline": {}})
