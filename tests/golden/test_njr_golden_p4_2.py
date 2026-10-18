"""Golden NJR snapshots for every builder (roadmap P4-2, step 1).

Each NJR builder applies its own subset of policies (audit C2).  Before any of them is folded into a single compile
core, the exact record each one produces today is pinned here, so a migration can only change an NJR on purpose: the
diff of a golden file is the review artifact.

Regenerate deliberately with ``STABLENEW_UPDATE_GOLDEN=1 pytest tests/golden`` and review the JSON diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.pipeline.training_njr_compiler import TrainingIntent, compile_training_intent
from tests.helpers.pipeline_fixtures_v2 import (
    make_batch_settings,
    make_minimal_pipeline_config,
    make_randomizer_plan_disabled,
)
from tests.pipeline.test_prompt_pack_job_builder import (
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "njr"
UPDATE = os.environ.get("STABLENEW_UPDATE_GOLDEN") == "1"


def _normalize(value: Any, tmp: Path) -> Any:
    """Make a snapshot machine-independent: temp paths become ``<tmp>`` with forward slashes."""

    # Round-trip through JSON so enums, tuples and mappings take the shape they are stored in.
    plain = json.loads(json.dumps(value, sort_keys=True, default=str))
    prefixes = sorted({str(tmp), tmp.as_posix()}, key=len, reverse=True)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str):
            # Path separators are an OS detail (some compilers normalize through ``Path``): compare with "/".
            for prefix in prefixes:
                if node.startswith(prefix):
                    node = "<tmp>" + node[len(prefix) :]
                    break
            return node.replace("\\", "/")
        return node

    return walk(plain)


def assert_golden(name: str, value: Any, tmp: Path) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    actual = json.dumps(_normalize(value, tmp), indent=1, sort_keys=True) + "\n"
    if UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
        return
    assert path.exists(), f"missing golden file {path}; run with STABLENEW_UPDATE_GOLDEN=1"
    expected = path.read_text(encoding="utf-8")
    assert actual.replace("\r\n", "\n") == expected.replace("\r\n", "\n"), (
        f"{name}: the NJR this builder produces changed. If that is intended, regenerate with "
        "STABLENEW_UPDATE_GOLDEN=1 and review the diff."
    )


def test_cli_builder(tmp_path: Path) -> None:
    record = build_cli_njr(
        prompt="a cat",
        batch_size=1,
        run_name="golden",
        config={
            "txt2img": {
                "model": "m.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
                "seed": 7,
            },
            "img2img": {"enabled": True, "denoising_strength": 0.4},
            "upscale": {"enabled": True, "upscaler": "Latent", "scale": 2.0},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        },
    )
    assert_golden("cli", record.to_dict(), tmp_path)


def test_job_builder_v2(tmp_path: Path) -> None:
    ids = SequentialIdGenerator()
    jobs = JobBuilderV2(time_fn=lambda: 1.0, id_fn=ids).build_jobs(
        base_config=make_minimal_pipeline_config(model="golden-model", steps=20, seed=12345),
        randomization_plan=make_randomizer_plan_disabled(),
        batch_settings=make_batch_settings(batch_runs=2),
    )
    assert_golden("job_builder_v2", [job.to_dict() for job in jobs], tmp_path)


def test_prompt_pack_builder(tmp_path: Path) -> None:
    config_manager = StubConfigManager(tmp_path)
    pack = _write_native_pack(
        config_manager.packs_dir / "golden-pack.json", text="A knight at dawn"
    )
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config_manager.packs_dir,
    )
    records = builder.build_jobs(
        [
            PackJobEntry(
                pack_id=pack.name,
                pack_name="Golden Pack",
                config_snapshot={},
                stage_flags={"txt2img": True, "upscale": True},
                randomizer_metadata={"enabled": False},
            )
        ]
    )
    assert_golden("prompt_pack", [record.to_dict() for record in records], tmp_path)


def test_reprocess_builder(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "navy").save(source)
    record = ReprocessJobBuilder().build_reprocess_job(
        input_image_paths=[str(source)],
        stages=["upscale"],
        config={"upscale": {"enabled": True, "upscaler": "R-ESRGAN 4x+", "scale": 2.0}},
        output_dir=str(tmp_path / "output"),
        prompt="p",
        negative_prompt="n",
        pack_name="Reprocess Golden",
    )
    snapshot = record.to_dict()
    assert len(snapshot["job_id"]) == 32  # a random identity: not part of the contract
    snapshot["job_id"] = "<job_id>"
    assert_golden("reprocess", snapshot, tmp_path)


def test_training_compiler(tmp_path: Path) -> None:
    record = compile_training_intent(
        TrainingIntent(
            config={
                "train_lora": {
                    "enabled": True,
                    "character_name": "Ada",
                    "image_dir": "images/ada",
                    "output_dir": "weights",
                    "epochs": 2,
                    "learning_rate": 0.0001,
                    "base_model": "sdxl",
                }
            },
            character_name="Ada",
            character_key="ada",
            output_dir="weights",
        ),
        id_fn=lambda: "train-1",
    )
    assert_golden("training", record.to_dict(), tmp_path)


def test_replay_compiler(tmp_path: Path) -> None:
    original = build_cli_njr(
        prompt="a cat",
        batch_size=1,
        run_name="golden",
        config={"txt2img": {"model": "m.safetensors", "steps": 4, "cfg_scale": 5.0, "seed": 7}},
    )
    replay = compile_replay_intent(ReplayIntent(original), id_fn=lambda: "replay-1")
    assert_golden("replay", replay.to_dict(), tmp_path)


@pytest.mark.parametrize(
    "name", ["cli", "job_builder_v2", "prompt_pack", "reprocess", "training", "replay"]
)
def test_every_golden_file_is_still_owned_by_a_test(name: str) -> None:
    assert (GOLDEN_DIR / f"{name}.json").exists() or UPDATE
