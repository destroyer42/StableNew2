from __future__ import annotations

from pathlib import Path

from src.pipeline.reprocess_builder import (
    ImageEditSpec,
    ReprocessJobBuilder,
    ReprocessSourceItem,
    extract_reprocess_output_paths,
)


def test_reprocess_builder_populates_img2img_stage_defaults_from_root_config(tmp_path: Path) -> None:
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"")
    builder = ReprocessJobBuilder()

    njr = builder.build_reprocess_job(
        input_image_paths=[image_path],
        stages=["img2img"],
        config={
            "steps": 24,
            "cfg_scale": 6.5,
            "sampler_name": "DPM++ 2M",
            "img2img": {"denoising_strength": 0.3},
        },
    )

    stage = njr.stage_chain[0]
    assert stage.stage_type == "img2img"
    assert stage.steps == 24
    assert stage.cfg_scale == 6.5
    assert stage.sampler_name == "DPM++ 2M"
    assert stage.denoising_strength == 0.3


def test_reprocess_builder_sets_provenance_and_prompt_source(tmp_path: Path) -> None:
    image_path = tmp_path / "portrait.png"
    image_path.write_bytes(b"")
    builder = ReprocessJobBuilder()

    njr = builder.build_reprocess_job(
        input_image_paths=[image_path],
        stages=["adetailer"],
        prompt="portrait photo",
        source="review_tab",
    )

    assert njr.prompt_source == "reprocess"  # type: ignore[attr-defined]
    assert njr.extra_metadata["submission_source"] == "review_tab"
    assert njr.extra_metadata["reprocess"]["schema"] == "stablenew.reprocess.v2.6"
    assert njr.extra_metadata["reprocess"]["input_image_paths"] == [str(image_path)]
    assert njr.extra_metadata["reprocess"]["requested_stages"] == ["adetailer"]


def test_grouped_reprocess_jobs_batches_only_compatible_inputs(tmp_path: Path) -> None:
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    image_c = tmp_path / "c.png"
    image_a.write_bytes(b"")
    image_b.write_bytes(b"")
    image_c.write_bytes(b"")
    builder = ReprocessJobBuilder()

    plan = builder.build_grouped_reprocess_jobs(
        items=[
            ReprocessSourceItem(
                input_image_path=str(image_a),
                prompt="portrait",
                model="modelA",
                config={"steps": 22},
            ),
            ReprocessSourceItem(
                input_image_path=str(image_b),
                prompt="portrait",
                model="modelA",
                config={"steps": 22},
            ),
            ReprocessSourceItem(
                input_image_path=str(image_c),
                prompt="portrait",
                model="modelB",
                config={"steps": 22},
            ),
        ],
        stages=["img2img"],
        fallback_config={"cfg_scale": 6.5},
        batch_size=2,
        source="review_tab",
    )

    assert plan.group_count == 2
    assert sorted(len(job.input_image_paths) for job in plan.jobs) == [1, 2]


def test_extract_reprocess_output_paths_prefers_artifact_contract(tmp_path: Path) -> None:
    output_one = tmp_path / "one.png"
    output_two = tmp_path / "two.png"
    output_one.write_bytes(b"")
    output_two.write_bytes(b"")
    record = type("Record", (), {"output_paths": [], "input_image_paths": ["a", "b"]})()

    paths = extract_reprocess_output_paths(
        record,
        {
            "variants": [
                {
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "artifact_type": "image",
                        "primary_path": str(output_one),
                        "output_paths": [str(output_one)],
                    }
                },
                {
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "artifact_type": "image",
                        "primary_path": str(output_two),
                        "output_paths": [str(output_two)],
                    }
                },
            ]
        },
    )

    assert paths == [str(output_one), str(output_two)]


def test_grouped_reprocess_jobs_preserve_image_edit_mask_config(tmp_path: Path) -> None:
    image_path = tmp_path / "input.png"
    mask_path = tmp_path / "mask.png"
    image_path.write_bytes(b"")
    mask_path.write_bytes(b"")
    builder = ReprocessJobBuilder()

    plan = builder.build_grouped_reprocess_jobs(
        items=[
            ReprocessSourceItem(
                input_image_path=str(image_path),
                prompt="repair eyes",
                image_edit=ImageEditSpec(mask_image_path=str(mask_path), mask_blur=8),
            )
        ],
        stages=["img2img"],
        fallback_config={"img2img": {"denoising_strength": 0.25}},
        source="image_edit",
    )

    assert len(plan.jobs) == 1
    job = plan.jobs[0]
    assert job.stage_chain[0].stage_type == "img2img"
    assert job.stage_chain[0].extra["mask_image_path"] == str(mask_path)
    assert job.stage_chain[0].extra["mask_blur"] == 8
    source_item = job.extra_metadata["reprocess"]["source_items"][0]
    assert source_item["image_edit"]["schema"] == "stablenew.image_edit.v2.6"
    assert source_item["image_edit"]["mask_image_path"] == str(mask_path)
