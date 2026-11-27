"""VID-CAND-LTX25 offline tool: suite derivation, frozen plan, eval-kit admission and the blind three-way sheet.

Synthetic images, synthetic run folders and a fake job service: nothing is queued to a real repository, no runtime
starts and no private file is read.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from tools.qualification.vid_cand382 import plan as base
from tools.qualification.vid_cand_ltx25 import __main__ as cli
from tools.qualification.vid_cand_ltx25 import plan as design
from tools.qualification.vid_cand_ltx25 import threeway

ARMS = ("a14b_base", "hy15_8step", "ltx25_distilled")


def _sources(folder: Path) -> tuple[Path, Path]:
    """Stand-ins for the frozen VID-CAND-382 stage 1 and stage 2 suites, with their images beside them."""

    paths = []
    for name, document in (
        ("stage1", base.example_suites()["stage1"]),
        ("stage2", base.example_suites()["stage2"]),
    ):
        for case in document["cases"]:
            image = folder / case["image"]
            image.parent.mkdir(parents=True, exist_ok=True)
            size = (96, 64) if "landscape" in case["image"] else (64, 96)
            Image.new("RGB", size, (90, 60, 30)).save(image)
        path = folder / f"source_{name}.suite.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths.append(path)
    return paths[0], paths[1]


def _build(tmp_path: Path) -> tuple[Path, Path, Path]:
    suites, private = tmp_path / "suites", tmp_path / "private"
    stage1, stage2 = _sources(suites)
    code = cli.main(
        [
            "build",
            "--stage1-suite",
            str(stage1),
            "--stage2-suite",
            str(stage2),
            "--suites-out",
            str(suites),
            "--plan-out",
            str(private),
            "--base-commit",
            "0" * 40,
        ]
    )
    assert code == 0
    return suites, private / design.PLAN_FILE, stage1


def test_the_ltx_suites_copy_the_382_cases_and_seeds_and_run_only_ltx_arms(tmp_path: Path) -> None:
    suites_dir, plan_file, stage1_path = _build(tmp_path)
    source = json.loads(stage1_path.read_text(encoding="utf-8"))
    built = {
        key: json.loads((suites_dir / name).read_text(encoding="utf-8"))
        for key, name in design.SUITE_FILES.items()
    }

    assert built["stage1"]["cases"] == source["cases"]  # images, prompts and negatives unchanged
    assert (built["stage1"]["seed"], built["stage2"]["seed"]) == (371, 372)
    for key, suite in built.items():
        [arm] = suite["arms"]
        assert arm["form"]["experimental_opt_in"] is True
        assert arm["form"]["frame_count"] == 121
        expected = design.LTX25_AUDIO_ARM if key == "audio" else design.LTX25_ARM
        assert arm["arm_id"] == suite["baseline_arm"] == expected
    # two different cases, so ComfyUI cannot answer the warm job from its cache
    cold, warm = built["stage0"]["cases"]
    assert (cold["image"], cold["prompt"]) != (warm["image"], warm["prompt"])
    assert all(c["prompt"].endswith(design.AUDIO_PROMPT_SUFFIX) for c in built["audio"]["cases"])
    jobs = sum(len(s["cases"]) * len(s["arms"]) for s in built.values())
    assert jobs == design.BUDGET["max_generations"] <= design.BUDGET["overall_cap"]

    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    for key, entry in plan["suites"].items():
        data = (suites_dir / entry["file"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), key
    # no speed ratio across sessions (agreed with VID-CAND-382)
    assert "faster" not in plan["thresholds"]
    assert plan["thresholds"]["speed"]["verdict"].startswith("none")


def test_a_rebuild_never_replaces_a_frozen_file(tmp_path: Path) -> None:
    suites_dir, plan_file, stage1_path = _build(tmp_path)
    with pytest.raises(SystemExit, match="never replaced"):
        cli.main(
            [
                "build",
                "--stage1-suite",
                str(stage1_path),
                "--stage2-suite",
                str(stage1_path),
                "--suites-out",
                str(suites_dir),
                "--plan-out",
                str(plan_file.parent),
                "--base-commit",
                "0" * 40,
            ]
        )


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


@pytest.mark.parametrize(("stage", "jobs"), [("stage1", 8), ("audio", 4)])
def test_the_eval_kit_previews_and_admits_the_ltx_suite(
    tmp_path: Path, stage: str, jobs: int
) -> None:
    suites_dir, _plan, _stage1 = _build(tmp_path)
    job_service = _JobService()
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(
            job_service=job_service,
            output_dir=str(tmp_path / "output"),
            sync_queue_state_after_direct_submission=lambda: None,
        )
    )

    plan = controller.preview_eval_run(suites_dir / design.SUITE_FILES[stage])

    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == jobs and job_service.calls == []
    for job in plan.jobs:
        config = job.njr.config["video_workflow"]
        assert (config["frame_count"], config["fps"]) == (121, 24)
        assert config["video_execution"]["experimental_opt_in"] is True
        accepted = {w["code"] for w in job.njr.extra_metadata["accepted_warnings"]}
        assert accepted == {"video_experimental_workflow", "video_licence_restriction"}
        target = config["source_preparation"]["target_dimensions"]
        assert (target["width"], target["height"]) in {(768, 1344), (1344, 768)}
    controller.submit_eval_run(plan)
    assert len(job_service.calls) == 1 and len(job_service.calls[0]) == jobs


# --- the three-way sheet ------------------------------------------------------------------------


def _run(root: Path, arm: str, cases: dict[str, str], *, seed: int = 371) -> Path:
    """A minimal finished eval run: ``run.json`` and ``metrics.json`` with one clip per case."""

    run_dir = root / f"run_{arm}"
    run_dir.mkdir(parents=True)
    cells = []
    for case_id in cases:
        clip = run_dir / f"{case_id}.mp4"
        clip.write_bytes(f"{arm}:{case_id}".encode())
        cells.append({"case_id": case_id, "arm_id": arm, "path": str(clip)})
    manifest = {
        "cases": [
            {"case_id": c, "image_sha256": c * 2, "prompt": p, "negative_prompt": "n"}
            for c, p in cases.items()
        ],
        "jobs": [{"case_id": c, "arm_id": arm, "seed": seed} for c in cases],
    }
    (run_dir / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "metrics.json").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    return run_dir


def _three_runs(tmp_path: Path) -> list[tuple[str, dict[str, dict[str, Any]]]]:
    prompts = {"c1": "walk", "c2": "wave", "c3": "turn", "c4": "sway"}
    runs = {
        "a14b_base": _run(tmp_path, "a14b_base", prompts),
        "hy15_8step": _run(tmp_path, "hy15_8step", prompts),
        # c3 ran with another prompt, c4 produced no clip
        "ltx25_distilled": _run(
            tmp_path, "ltx25_distilled", {"c1": "walk", "c2": "wave", "c3": "TURN"}
        ),
    }
    return [(arm, threeway.run_clips(runs[arm], arm)) for arm in ARMS]


def test_only_cases_with_identical_inputs_in_every_run_are_compared(tmp_path: Path) -> None:
    joined, skipped = threeway.join_cases(_three_runs(tmp_path))

    assert sorted(joined) == ["c1", "c2"]
    assert skipped == {"c3": "arms differ in prompt", "c4": "no clip for ltx25_distilled"}


def test_the_sheet_hides_arm_names_and_its_ranking_scores_back_to_arms(tmp_path: Path) -> None:
    joined, _skipped = threeway.join_cases(_three_runs(tmp_path))
    out = tmp_path / "compare"

    result = threeway.build_sheet(joined, seed=382, out_dir=out)

    assert result["sets"] == 2
    sheet_text = (out / threeway.SHEET_NAME).read_text(encoding="utf-8")
    assert not any(arm in sheet_text for arm in ARMS)
    assert sorted(p.name for p in (out / threeway.CLIP_FOLDER).iterdir()) == [
        f"s0{n}_{label}.mp4" for n in (1, 2) for label in "ABC"
    ]
    key = json.loads((out / threeway.KEY_NAME).read_text(encoding="utf-8"))["key"]
    for case_id, mapping in key.items():
        for label, arm in mapping.items():
            index = 1 if case_id == "c1" else 2
            assert (out / threeway.CLIP_FOLDER / f"s0{index}_{label}.mp4").read_bytes() == (
                f"{arm}:{case_id}".encode()
            )
    with pytest.raises(FileExistsError):
        threeway.build_sheet(joined, seed=382, out_dir=out)

    # The owner ranks LTX first and ties the other two, on every dimension.
    with (out / threeway.SHEET_NAME).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        mapping = key[row["case_id"]]
        first = next(label for label, arm in mapping.items() if arm == "ltx25_distilled")
        rest = "=".join(label for label in sorted(mapping) if label != first)
        for dimension in threeway.DIMENSIONS:
            row[f"{dimension}_ranking"] = f"{first}>{rest}"
    with (out / threeway.SHEET_NAME).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    scored = threeway.score_sheet(out / threeway.SHEET_NAME, out / threeway.KEY_NAME)

    assert scored["complete"] and scored["unanswered"] == 0
    assert scored["preference"]["a14b_base over ltx25_distilled"]["overall"] == 0.0
    assert scored["preference"]["a14b_base over hy15_8step"]["overall"] == 0.5


def test_the_command_refuses_to_write_inside_a_source_run(tmp_path: Path) -> None:
    prompts = {"c1": "walk"}
    first = _run(tmp_path, "a14b_base", prompts)
    second = _run(tmp_path, "ltx25_distilled", prompts)
    arguments = [
        "threeway",
        "--source",
        str(first),
        "a14b_base",
        "--source",
        str(second),
        "ltx25_distilled",
        "--seed",
        "382",
        "--out-dir",
    ]

    for inside in (first, second / "compare"):
        with pytest.raises(SystemExit, match="separate folder"):
            cli.main([*arguments, str(inside)])
    assert not (first / threeway.SHEET_NAME).exists() and not (second / "compare").exists()
    assert cli.main([*arguments, str(tmp_path / "compare")]) == 0


def test_the_shuffle_is_deterministic_and_does_not_follow_the_argument_order() -> None:
    orders = {case: threeway.shuffled(ARMS, 382, case) for case in map(str, range(20))}

    assert all(threeway.shuffled(ARMS[::-1], 382, c) == order for c, order in orders.items())
    assert len({tuple(order) for order in orders.values()}) > 2


@pytest.mark.parametrize("text", ["A>B", "A>B>B", "A>B>C>D", "x", "A>>B>C"])
def test_a_ranking_must_name_each_clip_exactly_once(text: str) -> None:
    with pytest.raises(ValueError, match="once"):
        threeway.parse_ranking(text, ["A", "B", "C"])
