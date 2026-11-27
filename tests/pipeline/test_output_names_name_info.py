"""NAME-INFO slice 2: descriptive names for new files and run folders (hermetic: temp roots, mocked backends)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.pipeline.output_naming import (
    DESCRIPTIVE_NAME,
    STEM_LIMIT,
    JobOutputNames,
    OutputName,
    read_image_naming,
    run_folder_label,
    short_id,
    stage_token,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.image_metadata import build_contract_kv, write_image_metadata
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.sequence_ledger import LEDGER_FILE_NAME
from src.video.sequence_locator import locate_ledger
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

CHECKPOINT = "photoMomentumSDXLNSFW_v20"
WHEN = datetime(2026, 11, 27, 16, 48, 12)
JOB = "8f87e4a2c0de4b1f9a2d1111222233334"


def picture(path: Path, *, stage="txt2img", history=(), pack=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16)).save(path)
    payload = {
        "stage": stage,
        "generation": {"model": CHECKPOINT},
        "stage_history": [{"stage": name, "model": CHECKPOINT} for name in history],
    }
    if pack:
        payload["prompt_pack"] = {"name": pack, "prompt_number": 1, "variant": 2}
    assert write_image_metadata(
        path, build_contract_kv(payload, job_id="source-job", run_id="run", stage=stage)
    )
    return path


def test_an_image_name_reads_path_model_pack_prompt_and_job():
    name = OutputName(
        WHEN,
        ("txt2img", "adetailer"),
        JOB,
        model="photoMomentum",
        pack="000-Style",
        prompt_number=1,
        variant=2,
    )
    assert name.stem() == "20261127-1648_txt2img+adetailer_photoMomentum_000-Style_p01v02_8f87e4a2"
    assert DESCRIPTIVE_NAME.fullmatch(f"{name.stem()}.png")


def test_a_clip_name_reads_engine_and_source_model():
    name = OutputName(
        datetime(2026, 11, 27, 14, 57),
        ("clip",),
        "969e487e785a5a1184df7002e52114e5",
        pack="000-Style",
        prompt_number=1,
        variant=2,
        engine="A14B",
        source_model="photoMomentum",
    )
    assert name.stem() == "20261127-1457_clip-A14B_from-photoMomentum_000-Style_p01_969e487e"


def test_unknown_parts_are_left_out():
    assert OutputName(WHEN, ("img2img",), JOB).stem() == "20261127-1648_img2img_8f87e4a2"


def test_long_and_unsafe_names_stay_safe_capped_and_unique_by_id():
    name = OutputName(
        WHEN,
        ("txt2img", "img2img", "adetailer", "adetailer", "upscale"),
        JOB,
        model='mo:del<>"|?*' * 6,
        pack="00_First Prompt/Variations\\for a very long pack name indeed",
        prompt_number=12,
        variant=34,
    )
    stem = name.stem(suffix="_i02")
    assert len(stem) <= STEM_LIMIT
    assert stem.endswith("_p12v34_8f87e4a2_i02")
    assert stem.startswith("20261127-1648_txt2img+img2img+adetailerx2+upscale_")
    assert DESCRIPTIVE_NAME.fullmatch(f"{stem}.png")
    deep = name.stem(run_dir=Path("C:/" + "deep/" * 40))
    assert len(deep) <= len(stem) and deep.endswith("_8f87e4a2")


def test_short_ids_come_from_the_job():
    assert short_id(JOB) == "8f87e4a2"
    assert short_id("test_job_1") == short_id("test_job_1") != short_id("test_job_2")
    assert len(short_id("learning-exp-v01")) == 8


def test_folder_labels_have_no_unknown_or_none():
    assert run_folder_label("000-Style", "photoMomentum") == "000-Style_photoMomentum"
    assert run_folder_label("", "photoMomentum", JOB) == "photoMomentum_8f87e4a2"
    assert run_folder_label("", "", JOB) == "8f87e4a2"
    assert stage_token(["upscaled", "video_workflow", "nonsense"]) == "upscale+clip"


def pack_njr(output: Path, **extra):
    return make_pipeline_njr(
        job_id=JOB,
        prompt_pack_id="000-Style",
        prompt_pack_name="000-Style",
        prompt_pack_row_index=0,
        variant_index=1,
        variant_total=3,
        base_model=CHECKPOINT,
        path_output_dir=str(output),
        config={"pipeline": {"output_route": "Pipeline"}, "model": CHECKPOINT, "prompt": "a"},
        **extra,
    )


def test_a_run_names_its_folder_and_each_stage_file(tmp_path):
    PipelineRunner._pack_folder_cache.clear()
    runner = PipelineRunner(
        api_client=MagicMock(), structured_logger=MagicMock(), runs_base_dir=str(tmp_path)
    )
    njr = pack_njr(
        tmp_path,
        stage_chain=[
            make_stage_config(model=CHECKPOINT),
            make_stage_config("adetailer", model=CHECKPOINT),
        ],
    )
    named: list[tuple[str, str]] = []

    def txt2img(*args, **kwargs):
        stem = kwargs.get("image_name") or args[3]
        named.append(("txt2img", stem))
        out = picture(Path(runner._job_run_dir) / f"{stem}.png")
        return {"path": str(out), "all_paths": [str(out)]}

    def adetailer(*args, **kwargs):
        stem = kwargs["image_name"]
        named.append(("adetailer", stem))
        return {"path": str(Path(runner._job_run_dir) / f"{stem}.png")}

    original = runner._prepare_run_dir

    def remember(job):
        dirs = original(job)
        runner._job_run_dir = dirs.run_dir
        return dirs

    runner._prepare_run_dir = remember
    runner._pipeline.run_txt2img_stage = MagicMock(side_effect=txt2img)
    runner._pipeline.run_adetailer_stage = MagicMock(side_effect=adetailer)

    result = runner.run_njr(njr)

    assert result.success is True, result.error
    [folder] = (tmp_path / "Pipeline").iterdir()
    assert folder.name.endswith("_000-Style_photoMomentum")
    stamp = named[0][1].split("_")[0]
    assert named == [
        ("txt2img", f"{stamp}_txt2img_photoMomentum_000-Style_p01v02_8f87e4a2"),
        ("adetailer", f"{stamp}_txt2img+adetailer_photoMomentum_000-Style_p01v02_8f87e4a2"),
    ]
    assert runner._job_output_names is None


def reprocess_njr(source: Path):
    return make_pipeline_njr(
        job_id="b1ab44a7ea9d5c69d6e039f878c9d168",
        source_kind="reprocess",
        input_image_paths=[str(source)],
        start_stage="adetailer",
        base_model=CHECKPOINT,
        stage_chain=[make_stage_config("adetailer", model=CHECKPOINT)],
    )


def test_a_reprocess_takes_pack_and_path_from_its_input(tmp_path):
    source = picture(tmp_path / "source.png", pack="000-Style")
    njr = reprocess_njr(source)
    names = JobOutputNames.for_job(njr, WHEN)

    assert names.folder_label(njr) == "000-Style_photoMomentum_b1ab44a7"
    assert names.image_stem("adetailer", input_path=source) == (
        "20261127-1648_txt2img+adetailer_photoMomentum_000-Style_p01v02_b1ab44a7"
    )
    assert names.pack_block() == {"name": "000-Style", "prompt_number": 1, "variant": 2}


def test_a_reprocess_of_a_picture_without_a_record_names_only_what_it_knows(tmp_path):
    source = tmp_path / "holiday photo.png"
    Image.new("RGB", (16, 16)).save(source)
    njr = reprocess_njr(source)

    names = JobOutputNames.for_job(njr, WHEN)

    assert names.folder_label(njr) == "photoMomentum_b1ab44a7"
    assert names.image_stem("adetailer", input_path=source) == (
        "20261127-1648_adetailer_photoMomentum_b1ab44a7"
    )


def test_a_clip_and_its_folder_name_the_source_pack_and_model(tmp_path):
    source = picture(tmp_path / "source.png", pack="000-Style")
    njr = make_pipeline_njr(
        job_id="969e487e785a5a1184df7002e52114e5",
        input_image_paths=[str(source)],
        config={"video_workflow": {"workflow_id": "wan22_i2v_a14b_4step_v1"}},
        stage_chain=[make_stage_config("video_workflow")],
    )
    runner = PipelineRunner(
        api_client=MagicMock(), structured_logger=MagicMock(), runs_base_dir=str(tmp_path)
    )
    runner._job_output_names = names = JobOutputNames.for_job(njr, WHEN)
    config = {"workflow_id": "wan22_i2v_a14b_4step_v1"}

    stem = runner._video_output_stem(njr, "video_workflow", config, str(source), run_dir=tmp_path)
    segment = runner._video_output_stem(
        njr,
        "video_workflow",
        config,
        str(source),
        run_dir=tmp_path,
        request_job_id=f"{njr.job_id}_seg01",
    )

    assert names.folder_label(njr) == "000-Style_photoMomentum_969e487e"
    assert stem == "20261127-1648_clip-A14B_from-photoMomentum_000-Style_p01_969e487e"
    assert segment == f"{stem}_seg01"


def test_the_pack_travels_in_the_image_record(tmp_path):
    from src.pipeline.executor import Pipeline

    pipeline = Pipeline(MagicMock(), MagicMock())
    pipeline._current_pack_block = {"name": "000-Style", "prompt_number": 3, "variant": 1}
    target = tmp_path / "out.png"
    payload = pipeline._build_image_metadata_payload(
        image_path=target, stage="txt2img", run_dir=tmp_path, manifest={}, image_size=(8, 8)
    )
    Image.new("RGB", (8, 8)).save(target)
    assert write_image_metadata(
        target, build_contract_kv(payload, job_id="j", run_id="r", stage="txt2img")
    )

    recorded = read_image_naming(target)

    assert (recorded.pack, recorded.prompt_number, recorded.variant) == ("000-Style", 3, 1)


def test_comfy_clips_take_the_name_and_working_frames_keep_theirs(tmp_path):
    class Client:
        def download_view(self, name, target, **_options):
            Path(target).write_bytes(b"x")
            return target

    history = {
        "outputs": {
            "1": {"videos": [{"filename": "wan22_job_00001_.mp4", "type": "output"}]},
            "2": {"images": [{"filename": "wan_a14b_job_00001_.png", "type": "output"}]},
        }
    }

    localized = ComfyWorkflowVideoBackend._localize_comfy_outputs(
        Client(), history, tmp_path, video_stem="20261127-1648_clip-A14B_8f87e4a2"
    )

    clip = localized["outputs"]["1"]["videos"][0]["filename"]
    frame = localized["outputs"]["2"]["images"][0]["filename"]
    assert Path(clip).name == "20261127-1648_clip-A14B_8f87e4a2.mp4"
    assert Path(frame).name == "wan_a14b_job_00001_.png"


@pytest.mark.parametrize(
    "folder",
    [
        "20261127_145726_000-Style_photoMomentum_969e487e",
        "20261022_212718_969e487e785a-unknown-none",  # an older folder
    ],
)
def test_a_sequence_ledger_is_found_in_new_and_old_folders(tmp_path, folder):
    job = "969e487e785a5a1184df7002e52114e5"
    ledger = tmp_path / "Reprocess" / folder / LEDGER_FILE_NAME
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"job_id": job}), encoding="utf-8")

    assert locate_ledger(job, [tmp_path]) == str(ledger.resolve())
