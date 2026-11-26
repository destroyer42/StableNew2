"""VID-CAND-382 offline tooling: frozen design, suite builder, read-only run analysis and blind pairwise helper.

Synthetic data only: a temporary run folder, a temporary SQLite job table and tiny PNG sources.  Nothing queues a job,
starts a runtime, reads a private file or touches a GPU.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.video.video_eval_suite import load_eval_suite
from tools.qualification.vid_cand382 import __main__ as cli
from tools.qualification.vid_cand382 import pairwise as pairing
from tools.qualification.vid_cand382 import plan as design
from tools.qualification.vid_cand382.verify import (
    analyze_run,
    job_rows,
    material_regression_cases,
    rating_stats,
    telemetry_by_arm,
    telemetry_summary,
    verdict,
    wall_by_arm,
)

BASE = datetime(2026, 11, 26, 9, 0, 0)


# --- the frozen design -------------------------------------------------------------------------


def _png(path: Path, shade: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 48), (shade, 20, 20)).save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clip371_shaped_suite(tmp_path: Path, name: str, ids: list[str], *, tag: str) -> Path:
    """A private-looking CLIP-371 suite: absolute image paths with pinned digests, prompts and negatives."""

    cases = []
    for index, case_id in enumerate(ids):
        image = tmp_path / "private" / f"{case_id}.png"
        cases.append(
            {
                "case_id": case_id,
                "image": str(image),
                "image_sha256": _png(image, 40 + index),
                "prompt": f"The woman in the image does action {case_id}.",
                "negative_prompt": design.STRUCTURED_NEGATIVE,
                "tags": [tag],
            }
        )
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "schema": design.SUITE_SCHEMA,
                "suite_id": "x",
                "seed": 1,
                "baseline_arm": "a",
                "cases": cases,
                "arms": [design.a14b_arm()],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_suites_have_the_planned_job_counts_arms_seeds_and_frame_counts() -> None:
    cases = [
        {"case_id": f"c{i}", "image": f"images/c{i}.png", "prompt": "p", "tags": []}
        for i in range(8)
    ]
    stage0 = design.build_stage0(cases[0])
    stage1 = design.build_stage1(cases)
    stage2_8, stage2_12 = design.build_stage2(cases, 8), design.build_stage2(cases, 12)

    assert [len(s["cases"]) * len(s["arms"]) for s in (stage0, stage1, stage2_8, stage2_12)] == [
        2,
        24,
        16,
        16,
    ]
    assert [c["case_id"] for c in stage0["cases"]] == [
        "s0_cold",
        "s0_warm",
    ]  # cold first, warm second
    assert [s["seed"] for s in (stage0, stage1, stage2_8)] == [382, 371, 372]
    frames = {arm["arm_id"]: arm["form"]["frame_count"] for arm in stage1["arms"]}
    assert frames == {"a14b_base": 81, "hy15_8step": 121, "hy15_12step": 121}
    assert [a["arm_id"] for a in stage1["arms"]] == [
        "a14b_base",
        "hy15_8step",
        "hy15_12step",
    ]  # baseline arm first
    assert [a["arm_id"] for a in stage2_12["arms"]] == ["a14b_base", "hy15_12step"]
    assert stage1["baseline_arm"] == "a14b_base"
    assert "experimental_opt_in" not in stage1["arms"][0]["form"]
    assert all(a["form"]["experimental_opt_in"] is True for a in stage1["arms"][1:])


def test_a_suite_over_the_eval_kit_cap_is_refused() -> None:
    cases = [{"case_id": f"c{i}", "image": "i.png", "prompt": "p"} for i in range(22)]

    with pytest.raises(ValueError, match="exceed"):
        design.build_stage1(cases)


def test_the_plan_writes_thresholds_fairness_stop_rules_and_budget_and_digests_stably(
    tmp_path: Path,
) -> None:
    cases = [{"case_id": f"c{i}", "image": f"images/c{i}.png", "prompt": "p"} for i in range(8)]
    suites = {"stage1": design.build_stage1(cases)}
    blobs = {"stage1": json.dumps(suites["stage1"]).encode()}

    plan = design.freeze_plan(
        suites, blobs, base_commit="abc", cases=[{"case_id": "c0", "image_sha256": "0" * 64}]
    )

    no_go = plan["thresholds"]["no_go"]
    assert no_go["host_commit_fraction_at_or_above"] == 0.95
    assert no_go["stage1_action_achieved_cases_below"] == 6
    assert no_go["critical_identity_breaks_above"] == 1
    assert (no_go["mean_source_fidelity_below"], no_go["mean_subject_stability_below"]) == (
        4.0,
        4.0,
    )
    assert (
        no_go["material_regression"]["points_at_least"] == 2
        and no_go["material_regression"]["cases_at_least"] == 2
    )
    assert plan["thresholds"]["as_good_or_better"]["stage1_mean_gap_at_most"] == 0.25
    assert (
        plan["thresholds"]["as_good_or_better"]["stage2_blind_pairwise_preference_at_least"] == 0.5
    )
    assert plan["thresholds"]["faster"]["warm_wall_time_median_ratio_at_most"] == 0.8
    assert any("0.97" in rule and "1 GiB" in rule for rule in plan["stop_rules"])
    assert any(
        "81 frames at 16 fps" in rule and "121 frames at 24 fps" in rule
        for rule in plan["fairness_rules"]
    )
    assert plan["budget"]["max_generations"] == 42 <= plan["budget"]["overall_cap"] == 60
    assert plan["budget"]["auto_retry"] is False
    assert plan["suites"]["stage1"]["jobs"] == 24
    assert plan["suites"]["stage1"]["sha256"] == hashlib.sha256(blobs["stage1"]).hexdigest()
    assert "none issued" in plan["authorization"]
    digest = design.plan_digest(plan)
    assert re.fullmatch(r"[0-9a-f]{64}", digest) and digest == design.plan_digest(
        json.loads(json.dumps(plan))
    )
    changed = json.loads(json.dumps(plan))
    changed["thresholds"]["faster"]["warm_wall_time_median_ratio_at_most"] = 0.9
    assert design.plan_digest(changed) != digest  # any change to a frozen threshold is a new digest


def test_suite_file_names_follow_the_canonical_eval_plan_naming() -> None:
    for name in design.SUITE_FILES.values():
        assert re.fullmatch(r"\d{8}_[a-z0-9_]+_v\d{3}\.suite\.json", name)


# --- the builder CLI over private-shaped cases -------------------------------------------------


def _build(tmp_path: Path, out: Path | None = None, *, extra: list[str] | None = None) -> int:
    stage1 = _clip371_shaped_suite(
        tmp_path, "s1.json", [f"img{i}_x_structured" for i in range(1, 9)], tag="structured"
    )
    stage2 = _clip371_shaped_suite(
        tmp_path, "s2.json", [f"fb{i}_x_structured" for i in range(1, 9)], tag="structured"
    )
    root = out or tmp_path / "out"
    return cli.main(
        [
            "build",
            "--stage1-suite",
            str(stage1),
            "--stage2-suite",
            str(stage2),
            "--suites-out",
            str(root / "video"),
            "--plan-out",
            str(root / "plan"),
            "--base-commit",
            "abc1234",
            *(extra or []),
        ]
    )


def test_build_writes_four_loadable_suites_and_a_plan_and_keeps_the_private_paths_out_of_the_plan(
    tmp_path: Path, capsys
) -> None:
    assert _build(tmp_path) == 0

    out = tmp_path / "out"
    jobs = {
        key: load_eval_suite(out / "video" / name).job_count
        for key, name in design.SUITE_FILES.items()
    }
    assert jobs == {"stage0": 2, "stage1": 24, "stage2_hy8": 16, "stage2_hy12": 16}
    plan_file = out / "plan" / "vid_cand_382_plan.v1.json"
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    for key, name in design.SUITE_FILES.items():
        assert (
            plan["suites"][key]["sha256"]
            == hashlib.sha256((out / "video" / name).read_bytes()).hexdigest()
        )
    text = plan_file.read_text(encoding="utf-8")
    assert "private" not in text and "woman" not in text  # no path and no prompt in the plan
    assert len(plan["cases"]) == 8
    digest = design.plan_digest(plan)
    assert f"PLAN DIGEST {digest}" in capsys.readouterr().out


def test_build_replaces_three_stage2_sources_with_the_new_hard_actions(tmp_path: Path) -> None:
    assert _build(tmp_path) == 0

    suite = json.loads(
        (tmp_path / "out" / "video" / design.SUITE_FILES["stage2_hy8"]).read_text(encoding="utf-8")
    )
    ids = [c["case_id"] for c in suite["cases"]]
    assert ids == [
        "fb1_x_structured",
        "fb2_x_structured",
        "fb3_hands_interact",
        "fb4_two_step",
        "fb5_x_structured",
        "fb6_fast_turn",
        "fb7_x_structured",
        "fb8_x_structured",
    ]
    by_id = {c["case_id"]: c for c in suite["cases"]}
    assert "clasps her hands" in by_id["fb3_hands_interact"]["prompt"]
    assert "two steps" in by_id["fb4_two_step"]["prompt"]
    assert "quickly" in by_id["fb6_fast_turn"]["prompt"]
    assert (
        by_id["fb3_hands_interact"]["image_sha256"]
        == by_id["fb3_hands_interact"]["image_sha256"].lower()
    )


def test_build_never_replaces_a_frozen_suite_and_refuses_repository_destinations(
    tmp_path: Path,
) -> None:
    assert _build(tmp_path) == 0
    with pytest.raises(SystemExit, match="exists"):
        _build(tmp_path)
    with pytest.raises(SystemExit, match="inside the repository"):
        _build(tmp_path, cli.ROOT / "docs" / "should_not_exist")
    assert not (cli.ROOT / "docs" / "should_not_exist").exists()


# --- read-only run analysis ---------------------------------------------------------------------


def _ts(seconds: float) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat()


def _suite_doc() -> dict[str, Any]:
    cases = [
        {
            "case_id": f"c{i}",
            "image": "i.png",
            "prompt": f"p{i}",
            "negative_prompt": "n",
            "tags": [],
        }
        for i in range(1, 5)
    ]
    return design.build_stage1(cases)


def _make_run(
    tmp_path: Path,
    *,
    walls: dict[str, list[float]],
    fail: dict[str, str] | None = None,
    gap: float = 1.0,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    """An arm-major run: a14b first, then hy 8-step, then hy 12-step, jobs back to back (``gap`` seconds apart)."""

    suite = _suite_doc()
    suite_file = tmp_path / "suite.json"
    suite_text = json.dumps(suite)
    suite_file.write_text(suite_text, encoding="utf-8")
    run_dir = tmp_path / "output" / "video_eval" / "run1"
    run_dir.mkdir(parents=True)
    db = tmp_path / "jobs.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute(
        "create table jobs (job_id text, status text, started_at text, completed_at text, error_message text)"
    )
    jobs, cells, clock = [], [], 0.0
    for arm in suite["arms"]:
        for case in suite["cases"]:
            job_id = f"{arm['arm_id']}-{case['case_id']}"
            wall = walls[arm["arm_id"]].pop(0)
            failed = (fail or {}).get(job_id)
            connection.execute(
                "insert into jobs values (?,?,?,?,?)",
                (
                    job_id,
                    "failed" if failed else "completed",
                    _ts(clock),
                    _ts(clock + wall),
                    failed,
                ),
            )
            clock += wall + gap
            jobs.append({"job_id": job_id, "case_id": case["case_id"], "arm_id": arm["arm_id"]})
            if failed:
                continue
            clip_dir = run_dir / "clips" / job_id
            (clip_dir / "manifests").mkdir(parents=True)
            (clip_dir / "clip.mp4").write_bytes(b"mp4-" + job_id.encode())
            form = arm["form"]
            (clip_dir / "manifests" / "m.json").write_text(
                json.dumps(
                    {
                        "workflow_id": form["workflow_id"],
                        "workflow_version": form["workflow_version"],
                        "actual_runtime": {
                            "comfyui_version": "0.38.0",
                            "pytorch_version": "2.14.0",
                        },
                        "compiled_workflow": {
                            "compiled_inputs": {
                                "seed": suite["seed"],
                                "prompt": case["prompt"],
                                "negative_prompt": case["negative_prompt"],
                                "frame_count": form["frame_count"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            cells.append(
                {
                    "case_id": case["case_id"],
                    "arm_id": arm["arm_id"],
                    "path": str(clip_dir / "clip.mp4"),
                }
            )
    connection.commit()
    connection.close()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "suite": {
                    "sha256": hashlib.sha256(suite_text.encode()).hexdigest(),
                    "seed": suite["seed"],
                },
                "arms": [{"arm_id": a["arm_id"], "overrides": a["form"]} for a in suite["arms"]],
                "jobs": jobs,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    return run_dir, suite_file, db, suite


def _ratings(path: Path, rows: dict[tuple[str, str], tuple[int, int, str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "case_id",
                "arm_id",
                "source_fidelity_1_to_5",
                "subject_stability_1_to_5",
                "requested_action",
                "critical_identity_break",
            ]
        )
        for (case, arm), (fidelity, stability, action, brk) in rows.items():
            writer.writerow([case, arm, fidelity, stability, action, brk])
    return path


def _all_rows(
    arm_scores: dict[str, tuple[int, int, str, str]],
) -> dict[tuple[str, str], tuple[int, int, str, str]]:
    return {(f"c{i}", arm): score for i in range(1, 5) for arm, score in arm_scores.items()}


WALLS = {
    "a14b_base": [170.0, 140.0, 142.0, 141.0],
    "hy15_8step": [150.0, 90.0, 92.0, 91.0],
    "hy15_12step": [190.0, 120.0, 122.0, 121.0],
}


def test_wall_time_is_split_cold_and_warm_per_arm_from_job_order_and_workflow_identity(
    tmp_path: Path,
) -> None:
    run_dir, _suite, db, _doc = _make_run(tmp_path, walls={k: list(v) for k, v in WALLS.items()})
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    wall = wall_by_arm(run, job_rows(db, (j["job_id"] for j in run["jobs"])))

    assert wall["a14b_base"]["cold"] == [170.0] and wall["a14b_base"]["warm"] == [
        140.0,
        142.0,
        141.0,
    ]
    assert wall["hy15_8step"]["cold"] == [150.0]  # an arm change is a cold start
    assert wall["hy15_8step"]["warm_median"] == 91.0 and wall["a14b_base"]["warm_median"] == 141.0
    assert wall["hy15_12step"]["cold_median"] == 190.0
    assert wall["a14b_base"]["states"] == {"completed": 4}


def test_a_gap_longer_than_the_keep_warm_grace_makes_the_next_job_cold(tmp_path: Path) -> None:
    run_dir, _suite, db, _doc = _make_run(
        tmp_path, walls={k: list(v) for k, v in WALLS.items()}, gap=300.0
    )
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    wall = wall_by_arm(run, job_rows(db, (j["job_id"] for j in run["jobs"])))

    assert wall["a14b_base"]["warm"] == [] and len(wall["a14b_base"]["cold"]) == 4


def test_the_job_table_is_opened_read_only(tmp_path: Path) -> None:
    _run, _suite, db, _doc = _make_run(tmp_path, walls={k: list(v) for k, v in WALLS.items()})
    before = db.read_bytes()

    rows = job_rows(db, ["a14b_base-c1", "missing"])

    assert set(rows) == {"a14b_base-c1"} and rows["a14b_base-c1"]["status"] == "completed"
    assert db.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True).execute("delete from jobs")


def test_analyze_run_reproduces_the_clip371_checks_and_reports_a_go_when_the_candidate_matches(
    tmp_path: Path,
) -> None:
    run_dir, suite_file, db, suite = _make_run(
        tmp_path, walls={k: list(v) for k, v in WALLS.items()}
    )
    good = (5, 5, "achieved", "no")
    ratings = _ratings(
        tmp_path / "ratings.csv",
        _all_rows(
            {
                "a14b_base": good,
                "hy15_8step": good,
                "hy15_12step": (4, 4, "partially_achieved", "no"),
            }
        ),
    )
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(
        json.dumps(
            {
                "samples": [
                    {"commit_fraction": 0.71, "available_ram_gb": 5.2, "vram_used_mib": 11000}
                ]
            }
        ),
        encoding="utf-8",
    )

    report = analyze_run(
        run_dir,
        jobs_db=db,
        suite_file=suite_file,
        suite_sha256=hashlib.sha256(suite_file.read_bytes()).hexdigest(),
        stage="stage1",
        baseline_arm="a14b_base",
        ratings_csv=ratings,
        telemetry_file=telemetry,
    )

    assert all(check["ok"] for check in report["checks"]), report["checks"]
    assert report["manifests_read"] == 12 and report["jobs"] == 12
    assert report["telemetry"] == {
        "samples": 1,
        "peak_commit_fraction": 0.71,
        "min_available_ram_gb": 5.2,
        "peak_vram_used_mib": 11000.0,
    }
    by_arm = {v["candidate_arm"]: v for v in report["verdicts"]}
    eight, twelve = by_arm["hy15_8step"], by_arm["hy15_12step"]
    assert not eight["no_go"] and eight["as_good_or_better"] is True
    assert eight["faster"] is True and eight["warm_median_ratio"] == round(91.0 / 141.0, 3)
    assert (
        twelve["as_good_or_better"] is False and twelve["faster"] is False
    )  # a full point below on two means; slower
    assert "owner's decision" in eight["decision"]
    assert report["wall_seconds"]["hy15_8step"]["states"] == {"completed": 4}


def test_a_wrong_suite_digest_or_prompt_fails_the_checks(tmp_path: Path) -> None:
    run_dir, suite_file, db, _doc = _make_run(
        tmp_path, walls={k: list(v) for k, v in WALLS.items()}
    )
    manifest = next(run_dir.glob("clips/hy15_8step-c1/manifests/m.json"))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["compiled_workflow"]["compiled_inputs"]["prompt"] = "something else"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    report = analyze_run(
        run_dir,
        jobs_db=db,
        suite_file=suite_file,
        suite_sha256="0" * 64,
        stage="stage1",
        baseline_arm="a14b_base",
    )

    failed = {c["check"] for c in report["checks"] if not c["ok"]}
    assert failed == {
        "suite sha256 matches the frozen plan",
        "seed, prompt, negative prompt and frame count are the suite's",
    }


def _stats_for(tmp_path: Path, scores: dict[str, tuple[int, int, str, str]]):
    ratings_path = _ratings(tmp_path / "r.csv", _all_rows(scores))
    from tools.qualification.vid_cand382.verify import read_ratings

    ratings = read_ratings(ratings_path)
    return ratings, {arm: rating_stats(ratings, arm) for arm in scores}


def _wall(base: float | None, cand: float | None) -> dict[str, dict[str, Any]]:
    return {"a14b_base": {"warm_median": base}, "hy15_8step": {"warm_median": cand}}


def _verdict(
    tmp_path: Path, scores, *, errors=None, telemetry=None, pairwise=None, stage="stage1", wall=None
):
    ratings, stats = _stats_for(tmp_path, scores)
    return verdict(
        stage=stage,
        candidate_arm="hy15_8step",
        baseline_arm="a14b_base",
        stats=stats,
        wall=wall or _wall(140.0, 90.0),
        ratings=ratings,
        errors=errors or {},
        telemetry=telemetry,
        pairwise=pairwise,
    )


GOOD = (5, 5, "achieved", "no")


def test_an_allocation_failure_is_a_no_go_whatever_the_ratings(tmp_path: Path) -> None:
    result = _verdict(
        tmp_path,
        {"a14b_base": GOOD, "hy15_8step": GOOD},
        errors={"hy15_8step": ["CUDA out of memory. Tried to allocate 2 GiB"]},
    )

    assert result["no_go"] and any("allocation" in r for r in result["no_go_reasons"])
    assert result["as_good_or_better"] is False


def test_host_commit_at_the_frozen_limit_is_a_no_go_and_missing_telemetry_is_not_evidence(
    tmp_path: Path,
) -> None:
    at_limit = _verdict(
        tmp_path, {"a14b_base": GOOD, "hy15_8step": GOOD}, telemetry={"peak_commit_fraction": 0.95}
    )
    none = _verdict(tmp_path, {"a14b_base": GOOD, "hy15_8step": GOOD})

    assert at_limit["no_go"] and "host commit 0.95" in at_limit["no_go_reasons"][0]
    assert not none["no_go"] and "host commit (no telemetry supplied)" in none["not_evidenced"]


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ((3, 5, "achieved", "no"), "mean fidelity 3.0"),
        ((5, 3, "achieved", "no"), "mean stability 3.0"),
        ((5, 5, "not_achieved", "no"), "action achieved 0/4"),
        ((5, 5, "achieved", "yes"), "4 critical identity breaks"),
    ],
)
def test_each_written_no_go_threshold_trips(tmp_path: Path, candidate, expected: str) -> None:
    result = _verdict(tmp_path, {"a14b_base": GOOD, "hy15_8step": candidate})

    assert result["no_go"], result
    assert any(expected in reason for reason in result["no_go_reasons"]), result["no_go_reasons"]


def test_one_break_is_tolerated_but_a_material_regression_on_two_cases_is_not(
    tmp_path: Path,
) -> None:
    ratings = {
        (f"c{i}", "a14b_base"): {
            "source_fidelity_1_to_5": "5",
            "subject_stability_1_to_5": "5",
            "critical_identity_break": "no",
        }
        for i in range(1, 5)
    }
    ratings[("c1", "hy15_8step")] = {
        "source_fidelity_1_to_5": "5",
        "subject_stability_1_to_5": "5",
        "critical_identity_break": "yes",
    }
    ratings[("c2", "hy15_8step")] = {
        "source_fidelity_1_to_5": "3",
        "subject_stability_1_to_5": "5",
        "critical_identity_break": "no",
    }
    ratings[("c3", "hy15_8step")] = {
        "source_fidelity_1_to_5": "4",
        "subject_stability_1_to_5": "4",
        "critical_identity_break": "no",
    }

    assert material_regression_cases(ratings, "a14b_base", "hy15_8step") == ["c1", "c2"]


def test_a_candidate_within_the_gap_is_as_good_and_one_beyond_it_is_not(tmp_path: Path) -> None:
    near = _verdict(tmp_path, {"a14b_base": GOOD, "hy15_8step": GOOD})
    far = _verdict(tmp_path, {"a14b_base": GOOD, "hy15_8step": (4, 5, "achieved", "no")})

    assert near["as_good_or_better"] is True
    assert (
        far["as_good_or_better"] is False and not far["no_go"]
    )  # 4.0 is not below 4.0, but 1.0 below baseline


def test_stage2_quality_comes_from_the_blind_pairwise_preference_and_ties_split(
    tmp_path: Path,
) -> None:
    pairs = {"overall_candidate_preference": 0.5}
    ok = _verdict(tmp_path, {"a14b_base": GOOD, "hy15_8step": GOOD}, stage="stage2", pairwise=pairs)
    low = _verdict(
        tmp_path,
        {"a14b_base": GOOD, "hy15_8step": GOOD},
        stage="stage2",
        pairwise={"overall_candidate_preference": 0.4375},
    )
    missing = _verdict(tmp_path, {"a14b_base": GOOD, "hy15_8step": GOOD}, stage="stage2")

    assert ok["as_good_or_better"] is True and low["as_good_or_better"] is False
    assert missing["as_good_or_better"] is None
    assert any("quality comparison" in item for item in missing["not_evidenced"])


def test_faster_needs_the_warm_median_ratio_at_or_under_point_eight(tmp_path: Path) -> None:
    scores = {"a14b_base": GOOD, "hy15_8step": GOOD}

    assert _verdict(tmp_path, scores, wall=_wall(100.0, 80.0))["faster"] is True
    assert _verdict(tmp_path, scores, wall=_wall(100.0, 81.0))["faster"] is False
    unmeasured = _verdict(tmp_path, scores, wall=_wall(100.0, None))
    assert unmeasured["faster"] is None and any(
        "warm wall-time" in n for n in unmeasured["not_evidenced"]
    )


def test_unrated_runs_report_what_is_not_evidenced_instead_of_passing(tmp_path: Path) -> None:
    result = verdict(
        stage="stage1",
        candidate_arm="hy15_8step",
        baseline_arm="a14b_base",
        stats={
            "hy15_8step": rating_stats({}, "hy15_8step"),
            "a14b_base": rating_stats({}, "a14b_base"),
        },
        wall=_wall(100.0, 70.0),
        ratings={},
        errors={},
        telemetry=None,
        pairwise=None,
    )

    assert not result["no_go"] and result["as_good_or_better"] is None
    assert any("owner ratings" in item for item in result["not_evidenced"])


def test_telemetry_is_optional_and_summarised_from_a_sample_list(tmp_path: Path) -> None:
    assert telemetry_summary(None) is None
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps([{"commit_fraction": 0.5}, {"commit_fraction": 0.9, "available_ram_gb": 1.5}]),
        encoding="utf-8",
    )

    assert telemetry_summary(path) == {
        "samples": 2,
        "peak_commit_fraction": 0.9,
        "min_available_ram_gb": 1.5,
        "peak_vram_used_mib": None,
    }


# --- blind pairwise ------------------------------------------------------------------------------


def _clips(tmp_path: Path, cases: int = 8) -> dict[str, dict[str, Path]]:
    clips: dict[str, dict[str, Path]] = {}
    for index in range(1, cases + 1):
        for arm in ("a14b_base", "hy15_8step"):
            path = tmp_path / "src" / f"deep_{arm}_dir" / f"c{index}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{arm}-{index}".encode())
            clips.setdefault(f"c{index}", {})[arm] = path
    return clips


def test_the_pairing_shuffles_deterministically_hides_the_arm_and_never_overwrites(
    tmp_path: Path,
) -> None:
    clips = _clips(tmp_path)
    one = pairing.build_pairing(
        clips,
        baseline_arm="a14b_base",
        candidate_arm="hy15_8step",
        seed=382,
        out_dir=tmp_path / "one",
    )
    two = pairing.build_pairing(
        clips,
        baseline_arm="a14b_base",
        candidate_arm="hy15_8step",
        seed=382,
        out_dir=tmp_path / "two",
    )
    other = pairing.build_pairing(
        clips,
        baseline_arm="a14b_base",
        candidate_arm="hy15_8step",
        seed=383,
        out_dir=tmp_path / "other",
    )

    key = lambda d: json.loads((d / "pairwise_key.json").read_text(encoding="utf-8"))  # noqa: E731
    assert one["pairs"] == 8 and not one["skipped"] and two["pairs"] == 8 and other["pairs"] == 8
    assert (
        key(tmp_path / "one")["key"] == key(tmp_path / "two")["key"]
    )  # a recorded seed reproduces the order
    assert key(tmp_path / "one")["key"] != key(tmp_path / "other")["key"]
    orders = {tuple(v.values()) for v in key(tmp_path / "one")["key"].values()}
    assert orders == {("a14b_base", "hy15_8step"), ("hy15_8step", "a14b_base")}  # both orders occur
    sheet = (tmp_path / "one" / "pairwise.csv").read_text(encoding="utf-8")
    assert "a14b" not in sheet and "hy15" not in sheet and "deep_" not in sheet  # blind
    assert sorted(p.name for p in (tmp_path / "one" / "pairwise_blind").iterdir())[:2] == [
        "p01_A.mp4",
        "p01_B.mp4",
    ]
    with pytest.raises(FileExistsError):
        pairing.build_pairing(
            clips,
            baseline_arm="a14b_base",
            candidate_arm="hy15_8step",
            seed=382,
            out_dir=tmp_path / "one",
        )
    assert all(
        path.is_file() for pair in clips.values() for path in pair.values()
    )  # the run's own clips are untouched


def test_a_case_missing_an_arm_is_listed_as_skipped_never_guessed(tmp_path: Path) -> None:
    clips = _clips(tmp_path, cases=3)
    del clips["c2"]["hy15_8step"]

    result = pairing.build_pairing(
        clips, baseline_arm="a14b_base", candidate_arm="hy15_8step", seed=1, out_dir=tmp_path / "p"
    )

    assert result["pairs"] == 2 and result["skipped"] == ["c2"]


def _fill(out: Path, picks: dict[str, tuple[str, str, str]], *, by_arm: bool = True) -> None:
    """Fill the sheet as the owner would: ``picks[case] = (arm preferred per dimension)`` or ``tie``."""

    meta = json.loads((out / "pairwise_key.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((out / "pairwise.csv").open(encoding="utf-8")))
    for row in rows:
        mapping = meta["key"][row["case_id"]]
        for dimension, arm in zip(pairing.DIMENSIONS, picks[row["case_id"]], strict=True):
            row[f"{dimension}_better"] = (
                "tie" if arm == "tie" else next(k for k, v in mapping.items() if v == arm)
            )
    with (out / "pairwise.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_scoring_maps_blind_choices_back_to_arms_and_splits_ties(tmp_path: Path) -> None:
    out = tmp_path / "p"
    pairing.build_pairing(
        _clips(tmp_path, 4),
        baseline_arm="a14b_base",
        candidate_arm="hy15_8step",
        seed=382,
        out_dir=out,
    )
    _fill(
        out,
        {
            "c1": ("hy15_8step", "hy15_8step", "hy15_8step"),
            "c2": ("hy15_8step", "a14b_base", "tie"),
            "c3": ("a14b_base", "a14b_base", "a14b_base"),
            "c4": ("tie", "tie", "tie"),
        },
    )

    result = pairing.score_pairing(out / "pairwise.csv", out / "pairwise_key.json")

    fidelity = result["per_dimension"]["fidelity"]
    assert (fidelity["candidate"], fidelity["baseline"], fidelity["tie"]) == (2, 1, 1)
    assert fidelity["candidate_preference"] == round((2 + 0.5) / 4, 4)
    assert result["per_dimension"]["stability"]["candidate_preference"] == round((1 + 0.5) / 4, 4)
    assert result["complete"] is True
    assert result["overall_candidate_preference"] == round((0.625 + 0.375 + 0.5) / 3, 4)


def test_an_unfilled_or_invalid_sheet_is_reported_not_scored(tmp_path: Path) -> None:
    out = tmp_path / "p"
    pairing.build_pairing(
        _clips(tmp_path, 2),
        baseline_arm="a14b_base",
        candidate_arm="hy15_8step",
        seed=1,
        out_dir=out,
    )

    blank = pairing.score_pairing(out / "pairwise.csv", out / "pairwise_key.json")
    assert blank["complete"] is False and blank["overall_candidate_preference"] is None

    rows = list(csv.DictReader((out / "pairwise.csv").open(encoding="utf-8")))
    rows[0]["fidelity_better"] = "left"
    with (out / "pairwise.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="not A, B or tie"):
        pairing.score_pairing(out / "pairwise.csv", out / "pairwise_key.json")


def test_telemetry_peaks_are_split_per_arm_by_the_arms_job_window(tmp_path: Path) -> None:
    run_dir, _suite, db, _doc = _make_run(tmp_path, walls={k: list(v) for k, v in WALLS.items()})
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rows = job_rows(db, (j["job_id"] for j in run["jobs"]))
    a14b_first, hy_first = rows["a14b_base-c1"], rows["hy15_8step-c1"]
    samples = [
        {"time": a14b_first["started_at"], "commit_fraction": 0.60, "vram_used_mib": 9000},
        {"time": hy_first["started_at"], "commit_fraction": 0.93, "vram_used_mib": 11800},
        {"time": hy_first["completed_at"], "commit_fraction": 0.80, "available_ram_gb": 1.2},
        {"commit_fraction": 0.99},  # no time: counted in the overall summary only
    ]
    path = tmp_path / "t.json"
    path.write_text(json.dumps(samples), encoding="utf-8")

    by_arm = telemetry_by_arm(path, run, rows)

    assert by_arm["a14b_base"]["peak_commit_fraction"] == 0.60
    assert by_arm["hy15_8step"]["peak_commit_fraction"] == 0.93
    assert by_arm["hy15_8step"]["peak_vram_used_mib"] == 11800.0
    assert by_arm["hy15_8step"]["min_available_ram_gb"] == 1.2
    assert by_arm["hy15_12step"]["samples"] == 0
    assert telemetry_summary(path)["peak_commit_fraction"] == 0.99
    assert telemetry_by_arm(None, run, rows) is None
