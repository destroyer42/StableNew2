"""NAME-INFO slice 1: what "More info" says about an output (hermetic: temp files and a stand-in job repository)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.pipeline.output_naming import model_short_name, recorded_naming, workflow_short_name
from src.review.output_info import OutputDescriber
from src.utils.image_metadata import build_contract_kv, write_image_metadata
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

CHECKPOINT = "photoMomentumSDXLNSFW_v20"
MADE = datetime(2026, 11, 27, 16, 48, 5, tzinfo=UTC)


def image(
    path: Path, job_id: str, *, stage="txt2img", history=(), model=CHECKPOINT, seeds=None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), "#224466").save(path)
    payload = {
        "job_id": job_id,
        "stage": stage,
        "generation": {"model": model},
        "stage_history": [{"stage": name, "model": CHECKPOINT} for name in history],
        "seeds": seeds or {},
    }
    assert write_image_metadata(
        path, build_contract_kv(payload, job_id=job_id, run_id="run", stage=stage)
    )
    return path


def manifest(output: Path, data: dict) -> None:
    folder = output.parent / "manifests"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{output.stem}.json").write_text(json.dumps(data), encoding="utf-8")


class Repository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    def add(self, njr) -> None:
        self.jobs[njr.job_id] = {"normalized_job": njr.to_queue_snapshot()}

    def get_job(self, job_id: str):
        found = self.jobs.get(job_id)
        return None if found is None else SimpleNamespace(snapshot=found)


@pytest.fixture
def world(tmp_path):
    repository = Repository()
    repository.add(
        make_pipeline_njr(
            job_id="job-pack",
            prompt_pack_id="000-Style",
            prompt_pack_name="000-Style",
            prompt_pack_row_index=0,
            variant_index=1,
            variant_total=3,
            base_model=CHECKPOINT,
            stage_chain=[make_stage_config(model=CHECKPOINT)],
        )
    )
    original = image(tmp_path / "Pipeline" / "run" / "original.png", "job-pack")
    manifest(original, {"actual_seed": 123456789012, "seed": -1})
    return SimpleNamespace(root=tmp_path, repository=repository, original=original)


def describe(world, path, **options):
    return OutputDescriber(
        world.repository, batch_identity=lambda job: {"name": "night batch"}
    ).describe(path, kind=options.pop("kind", "image"), made_at=MADE, **options)


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("photoMomentumSDXLNSFW_v20.safetensors [a1b2c3]", "photoMomentum"),
        ("sdxl\\ultriumV93_fp16.safetensors", "ultrium"),
        ("juggernautXL_v9", "juggernaut"),
        ("savsdxl_v6", "savsdxl"),
        ("perfectdeliberate_v10", "perfectdeliberate"),
        ("z_image_turbo_fp8", "zImageTurbo"),
        ("cyberrealistic_16fp", "cyberrealistic"),
        ("sd_xl_base_1.0", "SDXL-base"),
        ("flux1-dev-fp8", "flux1Dev"),
        ("Unknown", ""),
        ("", ""),
    ],
)
def test_checkpoint_short_names(name, short):
    assert model_short_name(name) == short


def test_workflow_short_names():
    assert workflow_short_name("wan22_i2v_a14b_4step_v1") == "A14B"
    assert workflow_short_name("wan22_ti2v_5b_i2v_v1") == "TI2V-5B"
    assert workflow_short_name("wan_animate2_drive_i2v_v1") == "Animate-2"
    assert workflow_short_name("ltx25_distilled_i2v_v1") == "LTX-2.5"
    assert workflow_short_name("hunyuan_video15_i2v_480p_8step_v1") == "HunyuanVideo"
    assert workflow_short_name("new_engine_v3") == "new-engine"


def test_every_catalog_workflow_has_a_short_name():
    from src.pipeline.output_naming import model_names
    from src.video.workflow_registry import build_builtin_workflow_specs

    listed = model_names()[1]
    missing = [
        spec.workflow_id
        for spec in build_builtin_workflow_specs()
        if spec.workflow_id not in listed
    ]
    assert missing == []


def test_recorded_naming_ignores_other_mappings():
    assert recorded_naming(None).stages == ()
    assert recorded_naming({"model": "x"}).stages == ()


def test_a_prompt_pack_image_names_its_path_model_prompt_and_seed(world):
    info = describe(world, world.original)
    assert info == {
        "stage_path": "txt2img",
        "model": "photoMomentum",
        "model_name": CHECKPOINT,
        "pack": "000-Style",
        "prompt_number": 1,
        "variant": 2,
        "made_at": "2026-11-27T16:48:05Z",
        "seed": "123456789012",
        "batch": "night batch",
    }


def test_a_reprocess_takes_pack_and_prompt_from_the_job_of_its_input(world):
    world.repository.add(
        make_pipeline_njr(
            job_id="job-fix",
            input_image_paths=[str(world.original)],
            start_stage="adetailer",
            source_kind="reprocess",
            base_model=CHECKPOINT,
            stage_chain=[make_stage_config("adetailer", model=CHECKPOINT)],
        )
    )
    result = image(
        world.root / "Reprocess" / "run" / "fixed.png",
        "job-fix",
        stage="adetailer",
        history=("txt2img",),
        seeds={"final_seed": 77},
    )

    info = describe(world, result)

    assert info["stage_path"] == "txt2img → ADetailer"
    assert (info["pack"], info["prompt_number"], info["variant"]) == ("000-Style", 1, 2)
    assert info["seed"] == "77"
    assert str(world.root) not in json.dumps(info)


def clip(world, job_id="job-clip", *, storyboard=False, workflow="wan22_i2v_a14b_4step_v1"):
    plan = {"storyboard": {"storyboard_id": "s"}} if storyboard else {}
    world.repository.add(
        make_pipeline_njr(
            job_id=job_id,
            input_image_paths=[str(world.original)],
            stage_chain=[make_stage_config("video_workflow", extra={"sequence_metadata": plan})],
        )
    )
    video = world.root / "Reprocess" / "clip" / "clip.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"not read")
    manifest(
        video,
        {
            "workflow_id": workflow,
            "workflow_version": "1.0.0",
            "source_image_path": str(world.original),
            "artifact": {"job_id": job_id},
        },
    )
    return video


def test_a_clip_names_its_engine_and_the_model_of_its_source(world):
    info = describe(world, clip(world), kind="video")

    assert info["stage_path"] == "clip (A14B) from photoMomentum"
    assert (info["model"], info["model_name"]) == ("A14B", "wan22_i2v_a14b_4step_v1 1.0.0")
    assert (info["pack"], info["prompt_number"], info["variant"]) == ("000-Style", 1, 2)
    assert str(world.root) not in json.dumps(info)


def test_a_storyboard_take_says_so(world):
    info = describe(world, clip(world, storyboard=True), kind="video")
    assert info["stage_path"] == "storyboard take (A14B) from photoMomentum"


def test_a_sequence_segment_job_id_finds_its_job(world):
    video = clip(world)
    recorded = json.loads((video.parent / "manifests" / "clip.json").read_text(encoding="utf-8"))
    recorded["artifact"]["job_id"] = "job-clip_seg01"
    manifest(video, recorded)
    assert describe(world, video, kind="video")["pack"] == "000-Style"


def test_a_file_with_no_record_shows_only_what_is_known(world):
    path = world.root / "elsewhere.png"
    Image.new("RGB", (8, 8)).save(path)

    info = OutputDescriber().describe(path, kind="image", made_at=MADE, seed="-1")

    assert info == {"made_at": "2026-11-27T16:48:05Z"}


def test_a_missing_repository_still_reads_the_file(world):
    info = OutputDescriber().describe(world.original, kind="image")
    assert (info["stage_path"], info["model"]) == ("txt2img", "photoMomentum")
    assert "pack" not in info
