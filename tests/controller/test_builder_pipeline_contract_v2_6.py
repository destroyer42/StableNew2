from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_models_v2 import NormalizedJobRecord


def _make_pack_files(tmp_path: Path, pack_id: str, prompt: str) -> None:
    pack_dir = tmp_path
    pack_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "pack_data": {
            "name": pack_id,
            "slots": [{"index": 0, "text": prompt, "negative": "bad"}],
        },
        "preset_data": {
            "pipeline": {"images_per_prompt": 1, "loop_count": 1},
            "txt2img": {
                "model": "test-model",
                "sampler_name": "Euler",
                "steps": 1,
                "cfg_scale": 7.0,
                "width": 256,
                "height": 256,
            },
        },
    }
    (pack_dir / f"{pack_id}.json").write_text(json.dumps(config), encoding="utf-8")


def make_minimal_pack_job_entry(pack_id: str, prompt: str) -> PackJobEntry:
    return PackJobEntry(
        pack_id=pack_id,
        pack_name="TestPack",
        config_snapshot={},
        prompt_text=prompt,
        negative_prompt_text="",
    )


@pytest.fixture()
def pack_dir(tmp_path: Path) -> Path:
    return tmp_path / "packs"


def test_prompt_pack_builder_produces_njrs_for_single_entry(
    pack_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    pack_id = "pack1"
    _make_pack_files(pack_dir, pack_id, "hello world")
    controller = PipelineController(config_manager=None)
    controller._config_manager.packs_dir = pack_dir  # type: ignore[attr-defined]

    entry = make_minimal_pack_job_entry(pack_id=pack_id, prompt="hello world")
    njrs = controller._build_njrs_from_pack_bundle([entry])
    assert len(njrs) >= 1
    assert all(isinstance(njr, NormalizedJobRecord) for njr in njrs)


def test_multiple_pack_entries_produce_multiple_njrs(pack_dir: Path):
    _make_pack_files(pack_dir, "pack1", "prompt1")
    _make_pack_files(pack_dir, "pack2", "prompt2")
    controller = PipelineController(config_manager=None)
    controller._config_manager.packs_dir = pack_dir  # type: ignore[attr-defined]

    entry1 = make_minimal_pack_job_entry(pack_id="pack1", prompt="prompt1")
    entry2 = make_minimal_pack_job_entry(pack_id="pack2", prompt="prompt2")
    njrs = controller._build_njrs_from_pack_bundle([entry1, entry2])
    assert len(njrs) >= 2
    pack_ids = {njr.prompt_pack_id for njr in njrs if hasattr(njr, "prompt_pack_id")}
    assert "pack1" in pack_ids and "pack2" in pack_ids


def test_pack_preview_overlays_current_frozen_global_prompt_policy(pack_dir: Path) -> None:
    _make_pack_files(pack_dir, "pack1", "hello")
    controller = PipelineController(config_manager=None)
    controller._config_manager.packs_dir = pack_dir  # type: ignore[attr-defined]
    controller.get_current_global_prompt_policy = lambda: {  # type: ignore[attr-defined]
        "positive_enabled": True,
        "positive_text": "current-positive",
        "negative_enabled": False,
        "negative_text": "current-negative",
    }
    stale_entry = make_minimal_pack_job_entry(pack_id="pack1", prompt="hello")
    stale_entry.config_snapshot = {
        "global_positive_prompt": "stale-positive",
        "global_negative_prompt": "stale-negative",
        "pipeline": {"apply_global_negative_txt2img": True},
    }

    njr = controller._build_njrs_from_pack_bundle([stale_entry])[0]

    assert njr.config["global_positive_prompt"] == "current-positive"
    assert njr.config["global_negative_prompt"] == "current-negative"
    assert njr.config["global_prompt_policy_source"] == "frozen_njr"
    assert njr.config["pipeline"]["apply_global_positive_txt2img"] is True
    assert njr.config["pipeline"]["apply_global_negative_txt2img"] is False


def test_no_pipeline_config_assembler_dependency():
    # Importing PipelineController should not raise ModuleNotFoundError for assembler
    try:
        importlib.import_module("src.controller.pipeline_controller")
    except ModuleNotFoundError as e:
        assert "pipeline_config_assembler" not in str(e)
