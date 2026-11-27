"""RG-170: registered rating sets and how phone answers reach each eval's own ratings contract."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from src.video.video_eval_rating_task import (
    RatingConflict,
    RatingSpecError,
    apply_answers,
    follow_up_spec,
    is_rated,
    load_rating_specs,
    register_rating_task,
    validate_spec,
)
from src.video.video_eval_ratings_store import RATING_COLUMNS, load_ratings, render_csv

NOW = "2026-11-27T12:00:00Z"


def _clip(root: Path, name: str) -> str:
    path = root / "clips" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode() * 4)
    return f"clips/{name}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


# --- A/B pairs: pairwise.csv ----------------------------------------------------------------------------------------


@pytest.fixture
def pairs(tmp_path: Path) -> dict:
    root = tmp_path / "blind"
    root.mkdir()
    header = "pair,case_id,clip_a,clip_b,fidelity_better,motion_better,notes\n"
    body = "".join(f"p0{n},case{n},clips/p0{n}_A.mp4,clips/p0{n}_B.mp4,,,\n" for n in (1, 2))
    (root / "pairwise.csv").write_text(header + body, encoding="utf-8")
    key = {
        "baseline_arm": "base",
        "candidate_arm": "new",
        "key": {"case1": {"A": "new", "B": "base"}, "case2": {"A": "base", "B": "new"}},
    }
    (root / "pairwise_key.json").write_text(json.dumps(key), encoding="utf-8")
    return {
        "schema": "stablenew.rating-set.v1",
        "task_id": "demo-pairs",
        "title": "Demo A/B",
        "kind": "pairs",
        "created_at": NOW,
        "root": str(root),
        "criteria": [
            {"criterion_id": name, "label": name, "type": "choice", "required": True}
            for name in ("fidelity_better", "motion_better")
        ],
        "items": [
            {
                "item_id": f"p0{n}",
                "context": "a request",
                "clips": [
                    {"clip_id": letter, "label": letter, "path": _clip(root, f"p0{n}_{letter}.mp4")}
                    for letter in "AB"
                ],
            }
            for n in (1, 2)
        ],
        "result": {"adapter": "pairwise_csv", "sheet": "pairwise.csv", "key": "pairwise_key.json"},
    }


def _pair_answers(first: str = "A", second: str = "B", notes: str = "") -> list[dict]:
    return [
        {
            "item_id": item,
            "clip_id": "",
            "values": {"fidelity_better": value, "motion_better": "tie"},
            "notes": notes if item == "p01" else "",
        }
        for item, value in (("p01", first), ("p02", second))
    ]


def test_pair_answers_fill_the_sheet_the_desktop_page_writes(pairs: dict) -> None:
    spec = validate_spec(pairs)
    assert not is_rated(spec)

    reveal = apply_answers(spec, _pair_answers(notes="close, call"))

    rows = _rows(Path(pairs["root"]) / "pairwise.csv")
    assert [row["fidelity_better"] for row in rows] == ["A", "B"]
    assert [row["motion_better"] for row in rows] == ["tie", "tie"]
    assert rows[0]["notes"] == "close, call"
    assert rows[0]["clip_a"] == "clips/p01_A.mp4"  # other columns untouched
    assert is_rated(spec)
    wins = reveal[0]
    assert wins["columns"] == ["Criterion", "base", "new", "Same"]
    assert wins["rows"][0] == ["fidelity_better", "0", "2", "0"]
    assert reveal[1]["rows"][0] == ["p01", "new", "base"]


def test_applying_the_same_answers_twice_changes_nothing(pairs: dict) -> None:
    spec = validate_spec(pairs)
    apply_answers(spec, _pair_answers(notes="n"))
    sheet = Path(pairs["root"]) / "pairwise.csv"
    before = sheet.read_bytes()

    apply_answers(spec, _pair_answers(notes="n"))

    assert sheet.read_bytes() == before


def test_a_desk_judgment_that_disagrees_refuses_the_whole_submission(pairs: dict) -> None:
    sheet = Path(pairs["root"]) / "pairwise.csv"
    sheet.write_text(
        sheet.read_text(encoding="utf-8").replace("p02_B.mp4,,,", "p02_B.mp4,A,,"), "utf-8"
    )
    before = sheet.read_bytes()

    with pytest.raises(RatingConflict) as error:
        apply_answers(validate_spec(pairs), _pair_answers(second="B"))

    assert error.value.reason == "already_rated"
    assert sheet.read_bytes() == before  # not even the untouched row


@pytest.mark.parametrize(
    "answers",
    [
        _pair_answers()[:1],
        [*_pair_answers(), {"item_id": "p09", "clip_id": "", "values": {}, "notes": ""}],
        _pair_answers(first="C"),
        [{**entry, "values": {"fidelity_better": "A"}} for entry in _pair_answers()],
        [{**entry, "values": {**entry["values"], "other": "A"}} for entry in _pair_answers()],
    ],
)
def test_answers_are_untrusted_and_checked_again_on_the_pc(pairs: dict, answers: list) -> None:
    sheet = Path(pairs["root"]) / "pairwise.csv"
    before = sheet.read_bytes()
    with pytest.raises(RatingConflict) as error:
        apply_answers(validate_spec(pairs), answers)
    assert error.value.reason == "invalid_record"
    assert sheet.read_bytes() == before


# --- scores: the run's ratings.csv ----------------------------------------------------------------------------------


@pytest.fixture
def scores(tmp_path: Path) -> dict:
    root = tmp_path / "blind"
    root.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    clips = [
        {
            "clip_id": letter,
            "label": letter,
            "path": _clip(root, f"c01_{letter}.mp4"),
            "key": f"c01_{letter}",
        }
        for letter in "AB"
    ]
    key = {
        "run_dir": str(run),
        "clips": {
            clip["key"]: {
                "case_id": "case1",
                "arm_id": f"arm_{clip['clip_id'].lower()}",
                "job_id": f"job-{clip['clip_id']}",
                "artifact_sha256": _sha(root / clip["path"]),
            }
            for clip in clips
        },
    }
    (root / "rating_key.json").write_text(json.dumps(key), encoding="utf-8")
    rows = []
    for entry in key["clips"].values():
        row = dict.fromkeys(RATING_COLUMNS, "")
        row.update({k: entry[k] for k in ("case_id", "arm_id", "job_id", "artifact_sha256")})
        rows.append(row)
    (run / "ratings.csv").write_bytes(render_csv(RATING_COLUMNS, rows).encode("utf-8"))
    return {
        "schema": "stablenew.rating-set.v1",
        "task_id": "demo-scores",
        "title": "Demo scores",
        "kind": "scores",
        "created_at": NOW,
        "root": str(root),
        "criteria": [
            {
                "criterion_id": "source_fidelity_1_to_5",
                "label": "Looks like the source",
                "type": "score",
                "required": True,
            },
            {
                "criterion_id": "critical_identity_break",
                "label": "Identity break?",
                "type": "enum",
                "required": True,
                "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
            },
        ],
        "items": [{"item_id": "c01", "clips": clips}],
        "result": {
            "adapter": "ratings_csv",
            "ratings": str(run / "ratings.csv"),
            "key": "rating_key.json",
        },
        "follow_up": {
            "task_id": "demo-scores-pick",
            "title": "Pick the next arm",
            "context": "Which arm runs next?",
            "options": [
                {"value": "arm_a", "label": "A", "recommended": True},
                {"value": "arm_b", "label": "B"},
            ],
            "result": {"adapter": "answer_file", "path": "pick.txt"},
        },
    }


def _score_answers() -> list[dict]:
    return [
        {
            "item_id": "c01",
            "clip_id": letter,
            "values": {"source_fidelity_1_to_5": score, "critical_identity_break": "no"},
            "notes": "fine" if letter == "A" else "",
        }
        for letter, score in (("A", "5"), ("B", "3"))
    ]


def test_scores_land_in_the_runs_ratings_csv_beside_their_clip_digest(scores: dict) -> None:
    spec = validate_spec(scores)
    reveal = apply_answers(spec, _score_answers())

    ratings = load_ratings(scores["result"]["ratings"])
    by_job = {row["job_id"]: row for row in ratings.rows}
    assert by_job["job-A"]["source_fidelity_1_to_5"] == "5"
    assert by_job["job-A"]["critical_identity_break"] == "no"
    assert by_job["job-A"]["notes"] == "fine"
    assert by_job["job-B"]["source_fidelity_1_to_5"] == "3"
    assert is_rated(spec)
    assert reveal[0]["columns"] == ["Arm", "Looks like the source", "Identity break?"]
    assert reveal[0]["rows"] == [["arm_a", "5.00", "no 1"], ["arm_b", "3.00", "no 1"]]
    assert reveal[1]["rows"] == [["c01", "arm_a", "arm_b"]]


def test_a_row_bound_to_another_clip_is_refused(scores: dict) -> None:
    path = Path(scores["result"]["ratings"])
    loaded = load_ratings(path)
    rows = [{**row, "artifact_sha256": "0" * 64} for row in loaded.rows]
    path.write_bytes(render_csv(loaded.header, rows).encode("utf-8"))

    with pytest.raises(RatingConflict) as error:
        apply_answers(validate_spec(scores), _score_answers())
    assert error.value.reason == "clip_changed"


def test_a_blind_clip_that_is_not_the_keys_artifact_is_refused(scores: dict) -> None:
    (Path(scores["root"]) / "clips" / "c01_A.mp4").write_bytes(b"replaced")
    with pytest.raises(RatingConflict) as error:
        apply_answers(validate_spec(scores), _score_answers())
    assert error.value.reason == "clip_changed"


def test_the_follow_up_pick_exists_only_after_the_reveal(scores: dict) -> None:
    spec = validate_spec(scores)
    reveal = apply_answers(spec, _score_answers())

    follow = follow_up_spec(spec, reveal)

    assert follow is not None
    assert (follow["task_id"], follow["kind"], follow["follow_up_of"]) == (
        "demo-scores-pick",
        "choice",
        "demo-scores",
    )
    assert "arm_a" in follow["items"][0]["context"]  # the reveal, to decide on
    chosen = validate_spec(follow)
    apply_answers(
        chosen, [{"item_id": "q1", "clip_id": "", "values": {"pick": "arm_b"}, "notes": ""}]
    )
    assert (Path(scores["root"]) / "pick.txt").read_text(encoding="utf-8") == "arm_b\n"
    with pytest.raises(RatingConflict):
        apply_answers(
            chosen, [{"item_id": "q1", "clip_id": "", "values": {"pick": "arm_a"}, "notes": ""}]
        )


# --- ranking and questions ------------------------------------------------------------------------------------------


def test_a_ranking_writes_its_own_sheet_and_mean_places(tmp_path: Path) -> None:
    root = tmp_path / "blind"
    root.mkdir()
    (root / "key.json").write_text(
        json.dumps({"key": {"c01": {"A": "x", "B": "y", "C": "z"}}}), encoding="utf-8"
    )
    spec = validate_spec(
        {
            "schema": "stablenew.rating-set.v1",
            "task_id": "three-way",
            "title": "Three way",
            "kind": "ranking",
            "created_at": NOW,
            "root": str(root),
            "criteria": [
                {"criterion_id": "motion", "label": "Motion", "type": "rank", "required": True}
            ],
            "items": [
                {
                    "item_id": "c01",
                    "clips": [
                        {"clip_id": c, "label": c, "path": _clip(root, f"{c}.mp4")} for c in "ABC"
                    ],
                }
            ],
            "result": {"adapter": "ranking_csv", "sheet": "ranking.csv", "key": "key.json"},
        }
    )

    reveal = apply_answers(
        spec, [{"item_id": "c01", "clip_id": "", "values": {"motion": "C>A=B"}, "notes": ""}]
    )

    assert _rows(root / "ranking.csv") == [{"item_id": "c01", "motion_order": "C>A=B", "notes": ""}]
    assert reveal[0]["rows"] == [["x", "2.50"], ["y", "2.50"], ["z", "1.00"]]


def _question(tmp_path: Path, **changes) -> dict:
    spec = {
        "schema": "stablenew.rating-set.v1",
        "task_id": "owner-question",
        "title": "Which default?",
        "kind": "choice",
        "created_at": NOW,
        "root": str(tmp_path),
        "criteria": [
            {
                "criterion_id": "pick",
                "label": "Pick one",
                "type": "enum",
                "required": True,
                "options": [
                    {"value": "yes", "label": "Yes", "recommended": True},
                    {"value": "no", "label": "No"},
                ],
            }
        ],
        "items": [{"item_id": "q1", "context": "Should it?"}],
        "result": {"adapter": "answer_file", "path": "answer.json"},
    }
    spec.update(changes)
    return spec


def test_a_questions_answer_is_a_json_file(tmp_path: Path) -> None:
    spec = validate_spec(_question(tmp_path))
    answers = [{"item_id": "q1", "clip_id": "", "values": {"pick": "yes"}, "notes": "go"}]

    assert apply_answers(spec, answers) == []
    apply_answers(spec, answers)  # idempotent

    written = json.loads((tmp_path / "answer.json").read_text(encoding="utf-8"))
    assert written["task_id"] == "owner-question"
    assert written["answers"] == answers
    assert is_rated(spec)


# --- registration ---------------------------------------------------------------------------------------------------


def test_registering_writes_one_file_per_task_and_never_silently_replaces(tmp_path: Path) -> None:
    folder = tmp_path / "rating_tasks"
    path = register_rating_task(_question(tmp_path), folder)
    assert path == folder / "owner-question.json"
    assert register_rating_task(_question(tmp_path), folder) == path  # the same content again
    with pytest.raises(RatingSpecError):
        register_rating_task(_question(tmp_path, title="Other"), folder)
    [(found, spec, error)] = load_rating_specs(folder)
    assert (found, spec.task_id, error) == (path, "owner-question", "")


def test_a_broken_file_is_reported_and_does_not_hide_the_others(tmp_path: Path) -> None:
    folder = tmp_path / "rating_tasks"
    register_rating_task(_question(tmp_path), folder)
    (folder / "broken.json").write_text("{", encoding="utf-8")
    entries = load_rating_specs(folder)
    assert [spec.task_id for _p, spec, _e in entries if spec] == ["owner-question"]
    assert [bool(error) for _p, spec, error in entries if spec is None] == [True]


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": "Bad Id"},
        {"kind": "stars"},
        {"title": r"see C:\private\folder"},
        {"items": [{"item_id": "q1", "context": r"\\server\share\x"}]},
        {"items": []},
        {"criteria": []},
        {"result": {"adapter": "email"}},
        {"result": {"adapter": "pairwise_csv", "sheet": "a.csv", "key": "k.json"}},
        {"unknown": 1},
    ],
)
def test_a_registration_that_could_leak_a_path_or_cannot_work_is_refused(tmp_path, changes) -> None:
    with pytest.raises(RatingSpecError):
        register_rating_task(_question(tmp_path, **changes), tmp_path / "rating_tasks")


def test_missing_clip_files_are_refused_at_registration(pairs: dict, tmp_path: Path) -> None:
    (Path(pairs["root"]) / "clips" / "p01_A.mp4").unlink()
    with pytest.raises(RatingSpecError):
        register_rating_task(pairs, tmp_path / "rating_tasks")


def test_a_damaged_sheet_refuses_the_submission_instead_of_raising(pairs: dict) -> None:
    sheet = Path(pairs["root"]) / "pairwise.csv"
    damaged = sheet.read_text(encoding="utf-8").replace("case1", '"case1"x')
    sheet.write_text(damaged, encoding="utf-8")
    spec = validate_spec(pairs)

    assert not is_rated(spec)
    with pytest.raises(RatingConflict) as error:
        apply_answers(spec, _pair_answers())
    assert error.value.reason == "write_failed"
    assert sheet.read_text(encoding="utf-8") == damaged


# --- the key file: checked at registration, and again before anything is written -----------------------------------

_ARMS = {"A": "new", "B": "base"}


@pytest.mark.parametrize(
    ("key", "said"),
    [
        ({"case1": _ARMS, "case2": _ARMS}, 'no "key" object'),  # VID-FRAME's old shape
        ([1, 2], "not a JSON object"),
        ({"key": {"case1": _ARMS}}, "p02"),
        ({"key": {"case1": _ARMS, "case2": {"A": "new"}}}, "clip B"),
        ({"key": {"case1": _ARMS, "case2": "base"}}, "p02"),
        ({"key": {"case1": _ARMS, "case2": {"A": "new", "B": ""}}}, "clip B"),
        ({"key": {"case1": _ARMS, "case2": {"A": "new", "B": r"C:\models\x"}}}, "PC path"),
    ],
)
def test_a_pair_key_that_cannot_reveal_every_pair_is_refused_before_anything_is_written(
    pairs: dict, tmp_path: Path, key: object, said: str
) -> None:
    root = Path(pairs["root"])
    (root / "pairwise_key.json").write_text(json.dumps(key), encoding="utf-8")
    sheet = (root / "pairwise.csv").read_bytes()

    with pytest.raises(RatingSpecError, match=re.escape(said)):
        register_rating_task(pairs, tmp_path / "rating_tasks")
    with pytest.raises(RatingConflict) as error:  # a key that changed after registration
        apply_answers(validate_spec(pairs), _pair_answers())

    assert not (tmp_path / "rating_tasks").exists()
    assert error.value.reason == "write_failed"
    assert (root / "pairwise.csv").read_bytes() == sheet


def test_a_pair_sheet_without_a_case_for_every_pair_is_refused(pairs: dict, tmp_path: Path) -> None:
    root = Path(pairs["root"])
    sheet = root / "pairwise.csv"
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("p02,case2,", "p02,,"), "utf-8")
    before = sheet.read_bytes()

    with pytest.raises(RatingSpecError, match="p02"):
        register_rating_task(pairs, tmp_path / "rating_tasks")
    with pytest.raises(RatingConflict):
        apply_answers(validate_spec(pairs), _pair_answers())

    assert sheet.read_bytes() == before


@pytest.mark.parametrize(
    "damage",
    [
        lambda key: key.pop("clips"),
        lambda key: key["clips"].pop("c01_B"),
        lambda key: key["clips"]["c01_B"].pop("arm_id"),
        lambda key: key["clips"]["c01_B"].update(job_id=""),
    ],
)
def test_a_score_key_that_does_not_cover_every_clip_is_refused(
    scores: dict, tmp_path: Path, damage
) -> None:
    path = Path(scores["root"]) / "rating_key.json"
    key = json.loads(path.read_text(encoding="utf-8"))
    damage(key)
    path.write_text(json.dumps(key), encoding="utf-8")
    ratings = Path(scores["result"]["ratings"])
    before = ratings.read_bytes()

    with pytest.raises(RatingSpecError, match="rating_key.json"):
        register_rating_task(scores, tmp_path / "rating_tasks")
    with pytest.raises(RatingConflict):
        apply_answers(validate_spec(scores), _score_answers())

    assert ratings.read_bytes() == before


def test_a_ranking_key_missing_a_clip_writes_no_sheet(tmp_path: Path) -> None:
    root = tmp_path / "blind"
    root.mkdir()
    (root / "key.json").write_text(json.dumps({"key": {"c01": {"A": "x"}}}), encoding="utf-8")
    data = {
        "schema": "stablenew.rating-set.v1",
        "task_id": "two-way",
        "title": "Two way",
        "kind": "ranking",
        "created_at": NOW,
        "root": str(root),
        "criteria": [
            {"criterion_id": "motion", "label": "Motion", "type": "rank", "required": True}
        ],
        "items": [
            {
                "item_id": "c01",
                "clips": [
                    {"clip_id": c, "label": c, "path": _clip(root, f"{c}.mp4")} for c in "AB"
                ],
            }
        ],
        "result": {"adapter": "ranking_csv", "sheet": "ranking.csv", "key": "key.json"},
    }

    with pytest.raises(RatingSpecError, match="clip B"):
        register_rating_task(data, tmp_path / "rating_tasks")
    with pytest.raises(RatingConflict):
        apply_answers(
            validate_spec(data),
            [{"item_id": "c01", "clip_id": "", "values": {"motion": "B>A"}, "notes": ""}],
        )

    assert not (root / "ranking.csv").exists()
