"""Prove response-index association survives partial saving; never infer historical seeds."""

import json
from unittest.mock import patch

import pytest

from src.pipeline.learning_sample_evidence import observed_sample
from tests.pipeline.test_executor_n_iter_filenames import _HEALTHY_RUNTIME_ADMISSION
from tests.pipeline.test_executor_n_iter_filenames import TestNIterFilenames as FilenameFixture


@pytest.mark.parametrize("seeds", [None, [], [42], [True, 43], [42, -1], [42, "43"]])
def test_missing_ambiguous_seed_vectors_create_no_association(seeds):
    assert observed_sample("image.png", 0, {"all_seeds": seeds}, 2, "job") is None


def test_actual_executor_partial_save_keeps_backend_response_index(tmp_path):
    fixture = FilenameFixture()
    fixture.setup_method()
    pipeline = fixture.pipeline
    pipeline._current_job_id = "job"
    response = {
        "images": ["a", "b", "c"],
        "info": json.dumps({"seed": 41, "all_seeds": [41, 42, 43]}),
    }

    def save(image, path, metadata_builder=None):
        return None if image == "b" else path

    with (
        patch.object(pipeline, "_generate_images", return_value=response),
        patch.object(pipeline, "_ensure_webui_true_ready"),
        patch.object(
            pipeline, "_ensure_runtime_admissible", return_value=_HEALTHY_RUNTIME_ADMISSION
        ),
        patch.object(pipeline, "_apply_webui_defaults_once"),
        patch("src.pipeline.executor.save_image_from_base64", side_effect=save),
    ):
        result = pipeline.run_txt2img_stage(
            prompt="test",
            negative_prompt="",
            config={
                "txt2img": {
                    "steps": 20,
                    "cfg_scale": 7.0,
                    "width": 512,
                    "height": 512,
                    "n_iter": 3,
                    "batch_size": 1,
                }
            },
            output_dir=tmp_path,
            image_name="learning",
            learning_sample_names=True,
        )
    samples = result["learning_samples"]["samples"]
    assert [s["seed"] for s in samples] == [41, 43]
    assert [s["sample_index"] for s in samples] == [0, 2]
    assert all(s["job_id"] == "job" for s in samples)
    assert [s["path"] for s in samples] == result["all_paths"]


def test_runtime_observation_reuses_owned_launch_only():
    from types import SimpleNamespace

    from src.pipeline.learning_sample_evidence import managed_runtime_observation

    manager = SimpleNamespace(
        owns_process=True,
        _process=SimpleNamespace(pid=100),
        _start_time=1000.0,
        ready_epoch=2,
        endpoint="http://test",
        runtime_identity="forge_webui",
    )
    before = managed_runtime_observation(manager)
    assert before["ready_epoch"] == 2
    manager.ready_epoch = 3
    assert managed_runtime_observation(manager) != before
    manager.owns_process = False
    assert managed_runtime_observation(manager) is None
    assert managed_runtime_observation(None) is None
