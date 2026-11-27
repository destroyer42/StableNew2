"""Blind three-way ranking across eval runs: A14B, HunyuanVideo 1.5 and LTX-2.5 clips of the same case.

The clips come from different runs, so every case is first checked to have the same source image, prompt, negative
prompt and seed in each run; a case that differs or lacks an arm is listed as skipped, never guessed.  Clips are copied
to neutral names with the order shuffled per case from a recorded seed.  The owner writes one ranking per dimension, for
example ``B>A=C``.  The runs are only read, and nothing is overwritten.  An agent never fills the sheet.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

DIMENSIONS = ("fidelity", "stability", "motion")
LABELS = "ABCD"
SHEET_NAME = "threeway.csv"
KEY_NAME = "threeway_key.json"
CLIP_FOLDER = "threeway_blind"
_FIXED = ("image_sha256", "prompt", "negative_prompt", "seed")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_clips(run_dir: Path, arm_id: str) -> dict[str, dict[str, Any]]:
    """``case_id -> {clip, image_sha256, prompt, negative_prompt, seed}`` for one arm of one run (read-only)."""

    manifest = _read(run_dir / "run.json")
    cases = {case["case_id"]: case for case in manifest["cases"]}
    seeds = {job["case_id"]: job["seed"] for job in manifest["jobs"] if job["arm_id"] == arm_id}
    if not seeds:
        raise ValueError(f"{run_dir.name} has no arm {arm_id!r}")
    metrics = _read(run_dir / "metrics.json")["cells"]
    cells = metrics if isinstance(metrics, list) else list(metrics.values())
    found: dict[str, dict[str, Any]] = {}
    for cell in cells:
        if cell.get("arm_id") != arm_id or not cell.get("path") or cell["case_id"] not in seeds:
            continue
        clip = Path(cell["path"])
        if not clip.is_absolute():
            # recorded relative to the checkout that ran the job
            clip = next(
                (base / clip for base in run_dir.resolve().parents if (base / clip).is_file()), clip
            )
        if not clip.is_file():
            continue
        case = cases[cell["case_id"]]
        found[cell["case_id"]] = {
            "clip": clip,
            "image_sha256": case.get("image_sha256"),
            "prompt": case.get("prompt"),
            "negative_prompt": case.get("negative_prompt"),
            "seed": seeds[cell["case_id"]],
        }
    return found


def join_cases(
    sources: Sequence[tuple[str, Mapping[str, Mapping[str, Any]]]],
) -> tuple[dict[str, dict[str, Path]], dict[str, str]]:
    """Cases every arm produced with identical inputs, and why each other case was skipped."""

    arms = [arm for arm, _ in sources]
    if not 2 <= len(arms) <= len(LABELS) or len(set(arms)) != len(arms):
        raise ValueError(f"need 2 to {len(LABELS)} distinct arms, got {arms}")
    joined: dict[str, dict[str, Path]] = {}
    skipped: dict[str, str] = {}
    for case_id in sorted({case for _, clips in sources for case in clips}):
        missing = [arm for arm, clips in sources if case_id not in clips]
        if missing:
            skipped[case_id] = f"no clip for {', '.join(missing)}"
            continue
        entries = [clips[case_id] for _, clips in sources]
        differing = [name for name in _FIXED if len({entry[name] for entry in entries}) > 1]
        if differing:
            skipped[case_id] = f"arms differ in {', '.join(differing)}"
            continue
        joined[case_id] = {arm: Path(clips[case_id]["clip"]) for arm, clips in sources}
    return joined, skipped


def shuffled(arms: Sequence[str], seed: int, case_id: str) -> list[str]:
    """Deterministic per-case order, independent of the order the arms or cases were given in."""

    return sorted(
        arms, key=lambda arm: hashlib.sha256(f"{seed}:{case_id}:{arm}".encode()).hexdigest()
    )


def build_sheet(
    joined: Mapping[str, Mapping[str, Path]], *, seed: int, out_dir: Path
) -> dict[str, Any]:
    sheet, key_path, folder = out_dir / SHEET_NAME, out_dir / KEY_NAME, out_dir / CLIP_FOLDER
    for existing in (sheet, key_path, folder):
        if existing.exists():
            raise FileExistsError(f"{existing} exists; comparison evidence is never replaced")
    if not joined:
        raise ValueError("no case has a clip for every arm with identical inputs")
    folder.mkdir(parents=True)
    rows: list[dict[str, str]] = []
    key: dict[str, dict[str, str]] = {}
    width = max(len(clips) for clips in joined.values())
    for index, case_id in enumerate(sorted(joined), start=1):
        clips = joined[case_id]
        row = {"set": f"s{index:02d}", "case_id": case_id}
        key[case_id] = {}
        for label, arm in zip(LABELS, shuffled(list(clips), seed, case_id), strict=False):
            name = f"s{index:02d}_{label}{clips[arm].suffix or '.mp4'}"
            shutil.copyfile(clips[arm], folder / name)  # bytes only: no file times or flags
            row[f"clip_{label.lower()}"] = f"{CLIP_FOLDER}/{name}"
            key[case_id][label] = arm
        rows.append(row)
    fields = [
        "set",
        "case_id",
        *(f"clip_{label.lower()}" for label in LABELS[:width]),
        *(f"{dimension}_ranking" for dimension in DIMENSIONS),
        "notes",
    ]
    with sheet.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)
    key_path.write_text(
        json.dumps({"seed": seed, "key": key}, indent=1, sort_keys=True), encoding="utf-8"
    )
    return {"sets": len(rows), "sheet": str(sheet), "key": str(key_path)}


def parse_ranking(text: str, labels: Sequence[str]) -> dict[str, int]:
    """``"B>A=C"`` -> ``{"B": 0, "A": 1, "C": 1}`` (lower is better); every label exactly once."""

    positions: dict[str, int] = {}
    for position, group in enumerate(text.replace(" ", "").upper().split(">")):
        for label in group.split("="):
            if label not in labels or label in positions:
                raise ValueError(f"ranking {text!r} must name each of {', '.join(labels)} once")
            positions[label] = position
    if len(positions) != len(labels):
        raise ValueError(f"ranking {text!r} must name each of {', '.join(labels)} once")
    return positions


def score_sheet(sheet: Path, key_file: Path) -> dict[str, Any]:
    """Per pair of arms and dimension: how often the first was ranked above the second (ties split)."""

    key = _read(key_file)["key"]
    totals: dict[str, dict[str, list[float]]] = {}
    unanswered = 0
    with sheet.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            mapping = key.get(row.get("case_id", ""))
            if mapping is None:
                raise ValueError(f"row {row.get('set')!r} has no key entry")
            for dimension in DIMENSIONS:
                text = (row.get(f"{dimension}_ranking") or "").strip()
                if not text:
                    unanswered += 1
                    continue
                places = parse_ranking(text, sorted(mapping))
                by_arm = {mapping[label]: place for label, place in places.items()}
                for first, second in combinations(sorted(by_arm), 2):
                    score = (
                        0.5
                        if by_arm[first] == by_arm[second]
                        else float(by_arm[first] < by_arm[second])
                    )
                    totals.setdefault(f"{first} over {second}", {}).setdefault(
                        dimension, []
                    ).append(score)
    preference = {
        pair: {
            **{d: round(sum(values) / len(values), 4) for d, values in per.items()},
            "overall": round(
                sum(sum(values) for values in per.values())
                / sum(len(values) for values in per.values()),
                4,
            ),
            "answered": sum(len(values) for values in per.values()),
        }
        for pair, per in totals.items()
    }
    return {
        "preference": preference,
        "unanswered": unanswered,
        "complete": bool(preference) and not unanswered,
    }


__all__ = [
    "DIMENSIONS",
    "build_sheet",
    "join_cases",
    "parse_ranking",
    "run_clips",
    "score_sheet",
    "shuffled",
]
