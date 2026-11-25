"""Deterministic fixtures for the PR-VID-MOTION-410 tests: synthetic media, suites and a fake-runtime controller.

Nothing here decodes a real video, starts a runtime or generates anything: a "driving video" is a few bytes with a video
suffix (the production builders only hash it) and a prepared record comes from an injected fake preparer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.video_eval_suite import SUITE_SCHEMA_V2

DRIVE_ID = "wan_animate2_drive_i2v_v1"
DRIVE_VERSION = "1.2.0"
TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class FakeJobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def make_image(path: Path, size=(64, 96), color=(120, 40, 90)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def make_video(path: Path, payload: bytes = b"driver-a") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def motion_block(driver: Path, **overrides: Any) -> dict[str, Any]:
    block: dict[str, Any] = {
        "driving": {"path": str(driver)},
        "action": "turns the head from left to right",
        "motion_prompt": "the person turns their head slowly to the right",
        "category": "head_turn",
        "expected_outcome": "The head rotates about 60 degrees to the right and holds; the body stays in place.",
    }
    block.update(overrides)
    return block


def drive_arm(
    arm_id: str = "baseline", *, frame_count: int = 49, **controls: float
) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": DRIVE_ID,
        "workflow_version": DRIVE_VERSION,
        "frame_count": frame_count,
        "experimental_opt_in": True,
    }
    if controls:
        form["operator_controls"] = dict(controls)
    return {"arm_id": arm_id, "label": arm_id, "backend": "video_workflow", "form": form}


def write_suite(
    tmp_path: Path, cases: list[dict[str, Any]], arms: list[dict[str, Any]], **extra: Any
) -> Path:
    data = {
        "schema": SUITE_SCHEMA_V2,
        "suite_id": "motion-core",
        "seed": 410,
        "cases": cases,
        "arms": arms,
        **extra,
    }
    path = tmp_path / "suite" / "motion.suite.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def controller(tmp_path: Path, *, preparer=None):
    job_service = FakeJobService()
    app = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    instance = VideoWorkflowController(app_controller=app)
    if preparer is not None:
        instance._motion_preparer = preparer  # type: ignore[attr-defined]
    return instance, job_service


def fake_prepared_record(spec, form, request, output_root, *, tmp: Path | None = None):
    """A deterministic stand-in for ``prepare_for_form``: a record whose files exist and whose contract is the real one."""

    from src.video.motion_source_plan import SCHEMA as SCHEMA_RECORD
    from src.video.motion_source_plan import motion_source_contract
    from src.video.motion_source_preparation import PREPARED_DIRNAME

    contract = motion_source_contract(spec, form.get("frame_count"))
    original = Path(str(form["pose_video_path"]))
    original_sha = sha(original)
    derived_payload = (
        f"{original_sha}|{request}|{contract.workflow_version}|{contract.output_frames}".encode()
    )
    derived_sha = hashlib.sha256(derived_payload).hexdigest()
    folder = Path(output_root) / PREPARED_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    derived = folder / f"{derived_sha}.mp4"
    derived.write_bytes(derived_payload)
    record = {
        "schema": SCHEMA_RECORD,
        "original": {"path": str(original), "sha256": original_sha},
        "derived": {
            "path": str(derived),
            "sha256": hashlib.sha256(derived.read_bytes()).hexdigest(),
            "frames": contract.output_frames,
            "frame_rate": f"{contract.output_fps}/1",
            "frames_md5_sha256": hashlib.sha256(derived_payload + b"frames").hexdigest(),
        },
        "settings": {"requested": dict(request), "start_frame": request.get("start", 0)},
        "contract": contract.to_record(),
        "plan": {"source_indices": list(range(contract.output_frames))},
        "processing": {"lossless": True},
    }
    # The derived file is content-addressed by its own hash.
    final = folder / f"{record['derived']['sha256']}.mp4"
    derived.replace(final)
    record["derived"]["path"] = str(final)
    return SimpleNamespace(prepared=True, record=record, message="", status="prepared")
