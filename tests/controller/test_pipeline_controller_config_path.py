
from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_models_v2 import NormalizedJobRecord

def _make_pack_files(tmp_path: Path, pack_id: str, prompt: str) -> None:
    packs_dir = tmp_path
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / f"{pack_id}.txt").write_text(f"{prompt}\nneg: bad\n", encoding="utf-8")
    config = {
        "version": "1.0",
        "pipeline": {"images_per_prompt": 1, "loop_count": 1},
        "txt2img": {
            "model": "test-model",
            "sampler_name": "Euler",
            "steps": 1,
            "cfg_scale": 7.0,
            "width": 256,
            "height": 256,
        },
    }
    (packs_dir / f"{pack_id}.json").write_text(json.dumps(config), encoding="utf-8")


def make_minimal_pack_job_entry(prompt="hello", pack_id="pack1"):
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

def test_controller_builds_njr_from_pack_bundle(pack_dir: Path):
    _make_pack_files(pack_dir, "pack1", "hello")
    controller = PipelineController(config_manager=None)
    controller._config_manager.packs_dir = pack_dir  # type: ignore[attr-defined]
    controller._config_manager.load_pack_config = lambda pid: json.loads(  # type: ignore[attr-defined]
        (pack_dir / f"{pid}.json").read_text(encoding="utf-8")
    )
    entry = make_minimal_pack_job_entry(pack_id="pack1")
    njrs = controller._build_njrs_from_pack_bundle([entry])
    assert len(njrs) >= 1
    assert all(isinstance(njr, NormalizedJobRecord) for njr in njrs)
    for njr in njrs:
        assert hasattr(njr, 'prompt_pack_id')
        assert isinstance(njr.prompt_pack_id, str)
