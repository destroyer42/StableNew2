"""Register rating sittings for the phone review gateway's "To rate" tab (RG-170).

    python -m tools.review_gateway_rating pairs BLIND_FOLDER --task-id ID --title TEXT
    python -m tools.review_gateway_rating scores BLIND_FOLDER --task-id ID --title TEXT [--pick VALUE=LABEL ...]
    python -m tools.review_gateway_rating choice --task-id ID --title TEXT --question TEXT --option VALUE=LABEL ...
    python -m tools.review_gateway_rating register RATING_SET.json
    python -m tools.review_gateway_rating list
    python -m tools.review_gateway_rating withdraw TASK_ID

``pairs`` reads a folder with ``pairwise.csv``, ``pairwise_key.json`` and ``HOW_TO_RATE.txt``; ``scores`` reads one
with ``rating_key.json``, ``clips/`` and ``sources/``. A registration is a file in this PC's rating folder; the running
app's sync worker sends it to the gateway. Nothing is queued or generated, no eval file is written here, and prompts
and arm ids are never printed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.app.review_gateway_ratings import default_rating_folder
from src.video.video_eval_rating_task import (
    SCHEMA,
    RatingSpecError,
    load_rating_specs,
    register_rating_task,
)
from src.video.video_eval_rubric import (
    ACTION_COLUMN,
    ACTION_VALUES,
    BREAK_COLUMN,
    BREAK_VALUES,
    OVERALL_COLUMN,
    SCORE_DIMENSIONS,
)

_PAIR_LABELS = {
    "fidelity_better": "Looks like the source",
    "stability_better": "Stable (no warping)",
    "motion_better": "Better motion",
}
#: The wording of the desktop score page for the two required scores.
_SCORE_LABELS = {
    "source_fidelity_1_to_5": "Looks like the source",
    "subject_stability_1_to_5": "Same subject throughout",
}
_PAIR_BLOCK = re.compile(r"(p\d+):\s*")
_PAIR_HELP = "Play both clips, then say which is better on each point. 'Same' means no difference you can see."
_SCORE_HELP = "Score each clip against the source picture, 5 is best. Blinding is partial: arms may differ in frame rate or size."
_BLIND_HELP = (
    " The review tab may show these clips with their model: submit before browsing them there."
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _contexts(text: str) -> dict[str, dict[str, str]]:
    """The ``pNN:`` blocks of ``HOW_TO_RATE.txt``: ``prompt:``, ``source image:`` or a plain line."""

    found: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        match = _PAIR_BLOCK.fullmatch(line)
        if match:
            current = found.setdefault(match.group(1), {})
        elif not line.strip():
            current = None
        elif current is not None:
            name, colon, value = line.strip().partition(": ")
            if colon and name == "source image":
                current["reference"] = value.strip()
            else:
                current["context"] = value.strip() if colon and name == "prompt" else line.strip()
    return found


def pairs_set(root: Path, task_id: str, title: str) -> dict[str, Any]:
    root = root.resolve()
    with (root / "pairwise.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = [name for name in reader.fieldnames or () if name.endswith("_better")]
        rows = list(reader)
    notes = root / "HOW_TO_RATE.txt"
    contexts = _contexts(notes.read_text(encoding="utf-8-sig")) if notes.is_file() else {}
    items = []
    for row in rows:
        pair = row["pair"]
        extra = contexts.get(pair, {})
        item: dict[str, Any] = {
            "item_id": pair,
            "clips": [
                {"clip_id": letter, "label": letter, "path": row[f"clip_{letter.lower()}"]}
                for letter in "AB"
            ],
        }
        if extra.get("context"):
            item["context"] = extra["context"][:2000]
        if extra.get("reference") and Path(extra["reference"]).is_file():
            item["reference"] = extra["reference"]
        items.append(item)
    return {
        "schema": SCHEMA,
        "task_id": task_id,
        "title": title,
        "kind": "pairs",
        "instructions": _PAIR_HELP + _BLIND_HELP,
        "created_at": _now(),
        "root": str(root),
        "criteria": [
            {
                "criterion_id": column,
                "label": _PAIR_LABELS.get(column, column.removesuffix("_better").replace("_", " ")),
                "type": "choice",
                "required": True,
            }
            for column in columns
        ],
        "items": items,
        "result": {"adapter": "pairwise_csv", "sheet": "pairwise.csv", "key": "pairwise_key.json"},
    }


def _score_criteria() -> list[dict[str, Any]]:
    def score(column: str, label: str, required: bool) -> dict[str, Any]:
        return {"criterion_id": column, "label": label, "type": "score", "required": required}

    def enum(column: str, label: str, values: Any) -> dict[str, Any]:
        options = [{"value": value, "label": text} for value, text in values]
        return {
            "criterion_id": column,
            "label": label,
            "type": "enum",
            "required": True,
            "options": options,
        }

    required = [score(column, label, True) for column, label in _SCORE_LABELS.items()]
    optional = [
        score(column, label, False)
        for column, label, _question in SCORE_DIMENSIONS
        if column not in _SCORE_LABELS
    ]
    return [
        *required,
        enum(ACTION_COLUMN, "Did the requested action happen?", ACTION_VALUES),
        enum(BREAK_COLUMN, "Critical identity break?", BREAK_VALUES),
        *optional,
        score(OVERALL_COLUMN, "Overall", False),
    ]


def scores_set(root: Path, task_id: str, title: str) -> dict[str, Any]:
    root = root.resolve()
    key = json.loads((root / "rating_key.json").read_text(encoding="utf-8"))
    run = Path(key["run_dir"])
    manifest = json.loads((run / "run.json").read_text(encoding="utf-8"))
    prompts = {case["case_id"]: str(case.get("prompt", "")) for case in manifest.get("cases", [])}
    grouped: dict[str, list[tuple[str, str]]] = {}
    for name, entry in sorted(key["clips"].items()):
        item_id, _underscore, letter = name.rpartition("_")
        grouped.setdefault(item_id, []).append((letter, entry["case_id"]))
    items = []
    for item_id, clips in grouped.items():
        item: dict[str, Any] = {
            "item_id": item_id,
            "context": prompts.get(clips[0][1], "")[:2000],
            "clips": [
                {
                    "clip_id": letter,
                    "label": letter,
                    "path": f"clips/{item_id}_{letter}.mp4",
                    "key": f"{item_id}_{letter}",
                }
                for letter, _case in clips
            ],
        }
        if (root / "sources" / f"{item_id}.png").is_file():
            item["reference"] = f"sources/{item_id}.png"
        items.append(item)
    return {
        "schema": SCHEMA,
        "task_id": task_id,
        "title": title,
        "kind": "scores",
        "instructions": _SCORE_HELP + _BLIND_HELP,
        "created_at": _now(),
        "root": str(root),
        "criteria": _score_criteria(),
        "items": items,
        "result": {
            "adapter": "ratings_csv",
            "ratings": str(run / "ratings.csv"),
            "key": "rating_key.json",
        },
    }


def _options(values: list[str], recommended: str | None) -> list[dict[str, Any]]:
    options = []
    for text in values:
        value, equals, label = text.partition("=")
        if not equals:
            raise RatingSpecError(f"an option is VALUE=LABEL, not {text!r}")
        option: dict[str, Any] = {"value": value, "label": label}
        if value == recommended:
            option["recommended"] = True
        options.append(option)
    return options


def choice_set(args: argparse.Namespace) -> dict[str, Any]:
    answers = args.answer_file or str(args.folder.resolve() / "answers" / f"{args.task_id}.json")
    return {
        "schema": SCHEMA,
        "task_id": args.task_id,
        "title": args.title,
        "kind": "choice",
        "created_at": _now(),
        "root": str(args.folder.resolve()),
        "criteria": [
            {
                "criterion_id": "pick",
                "label": "Pick one",
                "type": "enum",
                "required": True,
                "options": _options(args.option, args.recommended),
            }
        ],
        "items": [{"item_id": "q1", "context": args.question}],
        "result": {"adapter": "answer_file", "path": str(Path(answers).resolve())},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_gateway_rating",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--folder", type=Path, help="the rating folder (default: this PC's)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pairs", "scores", "choice"):
        sub = commands.add_parser(name)
        sub.add_argument("--task-id", required=True)
        sub.add_argument("--title", required=True)
        if name != "choice":
            sub.add_argument("blind_folder", type=Path)
    scores = commands.choices["scores"]
    scores.add_argument(
        "--pick", action="append", default=[], help="a follow-up option after the reveal"
    )
    scores.add_argument("--pick-title", default="Which runs next?")
    scores.add_argument(
        "--pick-file", default="pick.txt", help="where the pick is written, in BLIND_FOLDER"
    )
    choice = commands.choices["choice"]
    choice.add_argument("--question", required=True)
    choice.add_argument("--option", action="append", required=True)
    choice.add_argument("--recommended")
    choice.add_argument("--answer-file")
    commands.add_parser("register").add_argument("file", type=Path)
    commands.add_parser("list")
    commands.add_parser("withdraw").add_argument("task_id")
    return parser


def _status(folder: Path, task_id: str) -> str:
    try:
        state = json.loads((folder / "state" / f"{task_id}.json").read_bytes())
    except (OSError, ValueError):
        return "not sent yet"
    return str(state.get("status", "not sent yet"))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.folder = args.folder or default_rating_folder()
        if args.command == "list":
            for path, spec, error in load_rating_specs(args.folder):
                if spec is None:
                    print(f"{path.stem}  unreadable ({error})")
                else:
                    print(
                        f"{spec.task_id}  {spec.kind}  {len(spec.items)} item(s)  "
                        f"{_status(args.folder, spec.task_id)}"
                    )
            return 0
        if args.command == "withdraw":
            target = args.folder / f"{args.task_id}.json"
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", args.task_id) or not target.is_file():
                raise RatingSpecError(f"no registered task {args.task_id}")
            target.unlink()
            print(f"withdrawn {args.task_id}; the app removes it from the phone on its next sync")
            return 0
        if args.command == "register":
            data = json.loads(args.file.read_text(encoding="utf-8"))
        elif args.command == "pairs":
            data = pairs_set(args.blind_folder, args.task_id, args.title)
        elif args.command == "scores":
            data = scores_set(args.blind_folder, args.task_id, args.title)
            if args.pick:
                data["follow_up"] = {
                    "task_id": f"{args.task_id}-pick",
                    "title": args.pick_title,
                    "context": args.pick_title,
                    "options": _options(args.pick, None),
                    "result": {"adapter": "answer_file", "path": args.pick_file},
                }
        else:
            data = choice_set(args)
        path = register_rating_task(data, args.folder)
    except (OSError, ValueError, KeyError) as error:
        print(f"review_gateway_rating: {error}", file=sys.stderr)
        return 1
    print(f"registered {data['task_id']} ({data['kind']}, {len(data['items'])} item(s)): {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
