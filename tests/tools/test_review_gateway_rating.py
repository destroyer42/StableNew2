"""RG-170: registering the blind folders the evals already write. Synthetic folders and placeholder text only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.video.video_eval_rating_task import load_rating_specs
from src.video.video_eval_ratings_store import RATING_COLUMNS, render_csv
from tools.review_gateway_rating import main


def _only(folder: Path):
    [(_path, spec, error)] = load_rating_specs(folder)
    assert spec is not None, error
    return spec


@pytest.fixture
def pairwise_folder(tmp_path: Path) -> Path:
    root = tmp_path / "ck_blind"
    (root / "pairwise_blind").mkdir(parents=True)
    rows = ["pair,case_id,clip_a,clip_b,fidelity_better,stability_better,motion_better,notes"]
    for pair in ("p01", "p02"):
        for letter in "AB":
            (root / "pairwise_blind" / f"{pair}_{letter}.mp4").write_bytes(b"clip")
        rows.append(
            f"{pair},case_{pair},pairwise_blind/{pair}_A.mp4,pairwise_blind/{pair}_B.mp4,,,,"
        )
    (root / "pairwise.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    arms = {"A": "secret_arm_x", "B": "secret_arm_y"}
    (root / "pairwise_key.json").write_text(
        json.dumps({"key": {"case_p01": arms, "case_p02": arms}}), encoding="utf-8"
    )
    source = tmp_path / "source.png"
    source.write_bytes(b"png")
    (root / "HOW_TO_RATE.txt").write_text(
        "Rate each pair.\n\n"
        f"p01:\n  prompt: placeholder request one\n  source image: {source}\n\n"
        "p02:\n  one of the walk cases\n",
        encoding="utf-8",
    )
    return root


def test_a_pairwise_folder_registers_with_its_prompts_and_sources(
    pairwise_folder, tmp_path, capsys
):
    folder = tmp_path / "registry"
    args = [
        "--folder",
        str(folder),
        "pairs",
        str(pairwise_folder),
        "--task-id",
        "ck-ab",
        "--title",
        "CK A/B",
    ]

    assert main(args) == 0

    spec = _only(folder)
    assert (spec.kind, spec.adapter) == ("pairs", "pairwise_csv")
    assert [c["criterion_id"] for c in spec.criteria] == [
        "fidelity_better",
        "stability_better",
        "motion_better",
    ]
    assert [c["label"] for c in spec.criteria][0] == "Looks like the source"
    first, second = spec.items
    assert (first["item_id"], first["context"]) == ("p01", "placeholder request one")
    assert Path(first["reference"]).name == "source.png"
    assert second["context"] == "one of the walk cases" and "reference" not in second
    assert [c["path"] for c in first["clips"]] == [
        "pairwise_blind/p01_A.mp4",
        "pairwise_blind/p01_B.mp4",
    ]
    assert "placeholder request" not in capsys.readouterr().out  # prompts are never printed
    # The key is checked at registration, never copied into it.
    assert "secret_arm" not in (folder / "ck-ab.json").read_text(encoding="utf-8")


def test_a_score_folder_registers_against_its_runs_ratings_and_pick(tmp_path: Path, capsys) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps({"cases": [{"case_id": "case_one", "prompt": "placeholder request"}]}),
        encoding="utf-8",
    )
    (run / "ratings.csv").write_bytes(render_csv(RATING_COLUMNS, []).encode("utf-8"))
    root = tmp_path / "stage1_blind"
    (root / "clips").mkdir(parents=True)
    (root / "sources").mkdir()
    (root / "sources" / "c01.png").write_bytes(b"png")
    clips = {}
    for letter, arm in (("A", "secret_arm_x"), ("B", "secret_arm_y")):
        (root / "clips" / f"c01_{letter}.mp4").write_bytes(b"clip")
        clips[f"c01_{letter}"] = {
            "case_id": "case_one",
            "arm_id": arm,
            "job_id": f"job{letter}",
            "artifact_sha256": "0" * 64,
        }
    (root / "rating_key.json").write_text(
        json.dumps({"run_dir": str(run), "clips": clips}), encoding="utf-8"
    )
    folder = tmp_path / "registry"

    code = main(
        [
            "--folder",
            str(folder),
            "scores",
            str(root),
            "--task-id",
            "stage1",
            "--title",
            "Stage 1",
            "--pick",
            "x8=8 steps",
            "--pick",
            "x12=12 steps",
            "--pick-title",
            "Which step count next?",
            "--pick-file",
            "stage2_pick.txt",
        ]
    )

    assert code == 0
    spec = _only(folder)
    assert (spec.kind, spec.adapter) == ("scores", "ratings_csv")
    assert spec.result_path("ratings") == run / "ratings.csv"
    assert spec.required() == [
        "source_fidelity_1_to_5",
        "subject_stability_1_to_5",
        "requested_action",
        "critical_identity_break",
    ]
    [item] = spec.items
    assert (item["item_id"], item["context"], item["reference"]) == (
        "c01",
        "placeholder request",
        "sources/c01.png",
    )
    assert [(c["clip_id"], c["key"]) for c in item["clips"]] == [("A", "c01_A"), ("B", "c01_B")]
    assert "secret_arm" not in json.dumps(dict(spec.data))  # arms stay in the key file
    assert spec.data["follow_up"]["task_id"] == "stage1-pick"
    assert spec.data["follow_up"]["result"] == {"adapter": "answer_file", "path": "stage2_pick.txt"}
    out = capsys.readouterr().out
    assert "secret_arm" not in out and "placeholder request" not in out


def test_a_question_is_registered_listed_and_withdrawn(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "registry"
    base = ["--folder", str(folder)]

    code = main(
        [
            *base,
            "choice",
            "--task-id",
            "owner-q1",
            "--title",
            "Which default?",
            "--question",
            "Should it?",
            "--option",
            "yes=Yes",
            "--option",
            "no=No",
            "--recommended",
            "yes",
        ]
    )

    assert code == 0
    spec = _only(folder)
    assert spec.criteria[0]["options"][0] == {"value": "yes", "label": "Yes", "recommended": True}
    assert spec.result_path("path") == folder / "answers" / "owner-q1.json"
    assert main([*base, "list"]) == 0
    assert "owner-q1" in capsys.readouterr().out
    assert main([*base, "withdraw", "owner-q1"]) == 0
    assert load_rating_specs(folder) == []


def test_a_refused_registration_exits_with_its_reason(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--folder",
            str(tmp_path / "registry"),
            "choice",
            "--task-id",
            "Bad Id",
            "--title",
            "t",
            "--question",
            "q",
            "--option",
            "a=A",
            "--option",
            "b=B",
        ]
    )
    assert code == 1
    assert "task_id" in capsys.readouterr().err
