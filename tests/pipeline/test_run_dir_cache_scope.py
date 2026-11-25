"""The process-wide run-folder cache must be scoped to the output root.

Regression for the IMG-COMFY-381 ``[COLLISION] ... _copy1.png`` lines: a second runner with a different output root
(the ComfyUI arm) was handed the first runner's folder (the Forge arm) for the same pack/model/VAE, so its images were
written into the other arm's folder and only the collision failsafe kept them from overwriting.
"""

from datetime import datetime

import pytest

from src.pipeline.pipeline_runner import PipelineRunner


@pytest.fixture(autouse=True)
def _clean_cache():
    PipelineRunner._pack_folder_cache.clear()
    yield
    PipelineRunner._pack_folder_cache.clear()


def _resolve(route_root, now):
    return PipelineRunner._resolve_run_dir(
        route_root=route_root,
        route_cache_key="Pipeline:pack-model-none",
        folder_name="pack-model-none",
        now=now,
    )


def test_same_folder_key_under_different_output_roots_gets_separate_folders(tmp_path):
    first_root = tmp_path / "forge_webui" / "Pipeline"
    second_root = tmp_path / "comfyui" / "Pipeline"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)
    now = datetime(2026, 11, 25, 11, 49, 20)

    first = _resolve(first_root, now)
    second = _resolve(second_root, now)

    assert first.parent == first_root
    assert second.parent == second_root
    assert first != second


def test_same_output_root_still_reuses_its_folder(tmp_path):
    root = tmp_path / "Pipeline"
    root.mkdir()

    first = _resolve(root, datetime(2026, 11, 25, 11, 49, 20))
    second = _resolve(root, datetime(2026, 11, 25, 11, 50, 0))

    assert first == second
