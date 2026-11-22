"""Video eval suite: a fixed set of source images and prompts run against named arms (PR-VID-EVAL-320).

A suite is a versioned JSON file (``stablenew.video-eval-suite.v1``) that an operator keeps next to its
source images. Each *case* is one source image with a prompt; each *arm* is one way of turning an image
into a clip (a native SVD configuration or a Video Workflow form). An eval run queues every case under
every arm through the canonical path, so candidates are compared on the same inputs.

A case may instead be a *sequence* (VID-A14B-SVI-375): an ordered list of 2-12 segments, each with its own prompt,
that runs as ONE multi-segment job (``build_sequence_job``, PR-VID-SEQ-330) under each Video Workflow arm. Segment 0
starts from the case image and each later segment carries the previous segment's last frame; segment ``i`` uses the
suite seed plus ``i``, so every arm sees identical seeds. The job's primary video is the assembled sequence, so one
rating covers the whole sequence.

The suite only describes intent. Nothing here builds an NJR, touches a runtime or reads a video; loading
validates the file and pins each image by SHA-256 so a run can prove which bytes it used.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUITE_SCHEMA = "stablenew.video-eval-suite.v1"
ARM_BACKEND_SVD = "svd_native"
ARM_BACKEND_WORKFLOW = "video_workflow"
ARM_BACKENDS = (ARM_BACKEND_SVD, ARM_BACKEND_WORKFLOW)
#: One run admits every job at once; keep it to what one evening of local generation can finish.
MAX_EVAL_JOBS = 64
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
#: A sequence case has at least two segments (one is a plain case) and at most what one sequence job may run.
MIN_SEQUENCE_SEGMENTS = 2
MAX_SEQUENCE_SEGMENTS = 12


class EvalSuiteError(ValueError):
    """The suite file is unreadable or does not describe a runnable suite."""


@dataclass(frozen=True)
class EvalSegment:
    """One segment of a sequence case: its own prompt and, optionally, its own length."""

    prompt: str
    frame_count: int | None = None


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    image_path: Path
    image_sha256: str
    #: For a sequence case, segment 0's prompt (what the job's form-level prompt records).
    prompt: str
    negative_prompt: str = ""
    tags: tuple[str, ...] = ()
    #: Empty for a single-clip case; 2-12 segments for a sequence case.
    segments: tuple[EvalSegment, ...] = ()

    @property
    def is_sequence(self) -> bool:
        return bool(self.segments)

    def segment_seeds(self, suite_seed: int) -> tuple[int, ...]:
        """Segment ``i`` uses ``suite_seed + i``: fixed, and identical under every arm."""

        return tuple(suite_seed + index for index in range(len(self.segments)))


@dataclass(frozen=True)
class EvalArm:
    arm_id: str
    label: str
    backend: str
    #: ``svd_native``: an ``SVDConfig`` dict merged over the controller's default config.
    #: ``video_workflow``: form fields merged over the controller's default form.
    overrides: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requests_experimental(self) -> bool:
        return (
            bool(self.overrides.get("experimental_opt_in"))
            if self.backend == ARM_BACKEND_WORKFLOW
            else False
        )


@dataclass(frozen=True)
class EvalSuite:
    suite_id: str
    path: Path | None
    sha256: str
    description: str
    cases: tuple[EvalCase, ...]
    arms: tuple[EvalArm, ...]
    seed: int
    baseline_arm_id: str

    @property
    def job_count(self) -> int:
        return len(self.cases) * len(self.arms)

    def arm(self, arm_id: str) -> EvalArm:
        for arm in self.arms:
            if arm.arm_id == arm_id:
                return arm
        raise KeyError(arm_id)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvalSuiteError(message)


def _identifier(value: Any, what: str) -> str:
    text = str(value or "").strip()
    _require(
        bool(_ID_PATTERN.match(text)),
        f"{what} {text!r} must be 1-48 lowercase letters, digits, '_' or '-'",
    )
    return text


def _unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in ids:
        _require(value not in seen, f"duplicate {what}: {value}")
        seen.add(value)


def _load_case(raw: Any, suite_dir: Path) -> EvalCase:
    _require(isinstance(raw, Mapping), "every case must be an object")
    case_id = _identifier(raw.get("case_id"), "case_id")
    image_text = str(raw.get("image") or "").strip()
    _require(bool(image_text), f"case {case_id}: 'image' is required")
    image_path = Path(image_text).expanduser()
    if not image_path.is_absolute():
        image_path = suite_dir / image_path
    _require(image_path.is_file(), f"case {case_id}: image not found: {image_path}")
    actual = file_sha256(image_path)
    pinned = str(raw.get("image_sha256") or "").strip().lower()
    if pinned:
        _require(
            bool(_SHA256_PATTERN.match(pinned)), f"case {case_id}: image_sha256 is not a SHA-256"
        )
        _require(
            pinned == actual,
            f"case {case_id}: {image_path.name} changed since the suite pinned it "
            f"(expected {pinned[:12]}..., found {actual[:12]}...)",
        )
    segments = _load_segments(raw.get("segments"), case_id)
    prompt = str(raw.get("prompt") or "").strip()
    if segments:
        _require(
            not prompt,
            f"case {case_id}: a sequence case sets a prompt per segment, not a case 'prompt'",
        )
        prompt = segments[0].prompt
    _require(bool(prompt), f"case {case_id}: 'prompt' is required")
    tags = raw.get("tags") or []
    _require(isinstance(tags, list), f"case {case_id}: 'tags' must be a list")
    return EvalCase(
        case_id=case_id,
        image_path=image_path.resolve(),
        image_sha256=actual,
        prompt=prompt,
        negative_prompt=str(raw.get("negative_prompt") or "").strip(),
        tags=tuple(str(tag) for tag in tags),
        segments=segments,
    )


def _load_segments(raw: Any, case_id: str) -> tuple[EvalSegment, ...]:
    if raw is None:
        return ()
    _require(isinstance(raw, list), f"case {case_id}: 'segments' must be a list")
    _require(
        MIN_SEQUENCE_SEGMENTS <= len(raw) <= MAX_SEQUENCE_SEGMENTS,
        f"case {case_id}: a sequence case has {MIN_SEQUENCE_SEGMENTS}-{MAX_SEQUENCE_SEGMENTS} segments "
        f"(it has {len(raw)}); use 'prompt' for a single clip",
    )
    segments: list[EvalSegment] = []
    for position, item in enumerate(raw, start=1):
        label = f"case {case_id} segment {position}"
        _require(isinstance(item, Mapping), f"{label} must be an object")
        unknown = sorted(set(item) - {"prompt", "frame_count"})
        _require(not unknown, f"{label}: unknown field(s) {', '.join(unknown)}")
        prompt = str(item.get("prompt") or "").strip()
        _require(bool(prompt), f"{label}: 'prompt' is required")
        count = item.get("frame_count")
        _require(
            count is None or (isinstance(count, int) and not isinstance(count, bool) and count > 0),
            f"{label}: frame_count must be a positive whole number",
        )
        segments.append(EvalSegment(prompt=prompt, frame_count=count))
    return tuple(segments)


def _load_arm(raw: Any) -> EvalArm:
    _require(isinstance(raw, Mapping), "every arm must be an object")
    arm_id = _identifier(raw.get("arm_id"), "arm_id")
    backend = str(raw.get("backend") or "").strip()
    _require(
        backend in ARM_BACKENDS,
        f"arm {arm_id}: backend must be one of {', '.join(ARM_BACKENDS)}",
    )
    key = "svd" if backend == ARM_BACKEND_SVD else "form"
    overrides = raw.get(key) or {}
    _require(isinstance(overrides, Mapping), f"arm {arm_id}: '{key}' must be an object")
    if backend == ARM_BACKEND_WORKFLOW:
        _require(
            bool(str(overrides.get("workflow_id") or "").strip()),
            f"arm {arm_id}: form.workflow_id is required",
        )
        for frozen_by_case in ("prompt", "negative_prompt", "seed"):
            _require(
                frozen_by_case not in overrides,
                f"arm {arm_id}: form.{frozen_by_case} comes from the case and the suite seed",
            )
    else:
        _require(
            "seed" not in dict(overrides.get("inference") or {}),
            f"arm {arm_id}: svd.inference.seed comes from the suite seed",
        )
    return EvalArm(
        arm_id=arm_id,
        label=str(raw.get("label") or arm_id).strip() or arm_id,
        backend=backend,
        overrides=json.loads(json.dumps(overrides)),  # a detached, JSON-plain copy
    )


def load_eval_suite(path: str | Path) -> EvalSuite:
    suite_path = Path(path).expanduser()
    try:
        raw_bytes = suite_path.read_bytes()
    except OSError as exc:
        raise EvalSuiteError(f"cannot read eval suite {suite_path}: {exc}") from exc
    return parse_eval_suite(suite_path, raw_bytes)


def parse_eval_suite(suite_path: Path, raw_bytes: bytes) -> EvalSuite:
    """Validate one suite snapshot using the given path for relative references."""
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except ValueError as exc:
        raise EvalSuiteError(f"cannot read eval suite {suite_path}: {exc}") from exc
    _require(isinstance(data, Mapping), "an eval suite must be a JSON object")
    _require(
        data.get("schema") == SUITE_SCHEMA,
        f"unsupported eval suite schema {data.get('schema')!r} (expected {SUITE_SCHEMA})",
    )
    suite_id = _identifier(data.get("suite_id"), "suite_id")
    raw_cases = data.get("cases")
    raw_arms = data.get("arms")
    _require(
        isinstance(raw_cases, list) and bool(raw_cases), "an eval suite needs at least one case"
    )
    _require(isinstance(raw_arms, list) and bool(raw_arms), "an eval suite needs at least one arm")
    suite_dir = suite_path.resolve().parent
    cases = tuple(_load_case(raw, suite_dir) for raw in raw_cases)
    arms = tuple(_load_arm(raw) for raw in raw_arms)
    _unique([case.case_id for case in cases], "case_id")
    _unique([arm.arm_id for arm in arms], "arm_id")
    if any(case.is_sequence for case in cases):
        svd_arms = [arm.arm_id for arm in arms if arm.backend != ARM_BACKEND_WORKFLOW]
        _require(
            not svd_arms,
            f"sequence cases run as Video Workflow sequences; arm(s) {', '.join(svd_arms)} "
            f"use {ARM_BACKEND_SVD}",
        )
    _require(
        len(cases) * len(arms) <= MAX_EVAL_JOBS,
        f"{len(cases)} cases x {len(arms)} arms = {len(cases) * len(arms)} jobs; "
        f"one run admits at most {MAX_EVAL_JOBS}",
    )
    try:
        seed = int(data.get("seed", 0))
    except (TypeError, ValueError) as exc:
        raise EvalSuiteError("seed must be an integer") from exc
    _require(0 <= seed < 2**32, "seed must be in 0..2^32-1")
    baseline = str(data.get("baseline_arm") or arms[0].arm_id).strip()
    _require(baseline in {arm.arm_id for arm in arms}, f"baseline_arm {baseline!r} is not an arm")
    return EvalSuite(
        suite_id=suite_id,
        path=suite_path.resolve(),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        description=str(data.get("description") or "").strip(),
        cases=cases,
        arms=arms,
        seed=seed,
        baseline_arm_id=baseline,
    )


__all__ = [
    "ARM_BACKENDS",
    "ARM_BACKEND_SVD",
    "ARM_BACKEND_WORKFLOW",
    "MAX_EVAL_JOBS",
    "MAX_SEQUENCE_SEGMENTS",
    "MIN_SEQUENCE_SEGMENTS",
    "SUITE_SCHEMA",
    "EvalArm",
    "EvalCase",
    "EvalSegment",
    "EvalSuite",
    "EvalSuiteError",
    "file_sha256",
    "load_eval_suite",
]
