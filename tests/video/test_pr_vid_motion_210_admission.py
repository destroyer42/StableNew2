"""PR-VID-MOTION-210: a prepared motion source is verified and frozen at admission, and nothing else changes.

Drives the real Video Workflow controller with a fake JobService.  Most cases use a synthetic
prepared record (admission only hashes bytes), so they run without FFmpeg; the end-to-end agreement
cases use real FFmpeg and are skipped without it.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import re
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.pipeline.video import resolve_ffmpeg_executable
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.motion_source_plan import SCHEMA
from src.video.video_backend_types import VideoExecutionRequest
from src.video.video_workflow_batch import BatchRefused
from src.video.video_workflow_experiment import ExperimentRefused
from src.video.video_workflow_njr_builder import PREPARED_MOTION_SOURCE_FIELD
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from src.video.workflow_compiler import WorkflowCompiler

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None or resolve_ffprobe_executable() is None,
    reason="FFmpeg/FFprobe are not installed",
)
PROMPT_ID = "wan_animate2_prompt_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [str(njr.job_id) for njr in njrs]


def _stack(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app), service


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    clip = tmp_path / "driving.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 original clip bytes")
    return source, clip


def _record(
    tmp_path: Path,
    clip: Path,
    *,
    frames: int = 41,
    version: str = WAN_ANIMATE2_RUNTIME_VERSION,
    workflow_id: str = WAN_ANIMATE2_DRIVE_ID,
    start: int = 7,
    conversion: str = "none",
) -> dict[str, Any]:
    """A consistent record over real files (admission re-hashes bytes; it does not decode)."""

    folder = tmp_path / "output" / "prepared_driving_videos"
    folder.mkdir(parents=True, exist_ok=True)
    payload = f"prepared bytes {frames} {start} {conversion}".encode()
    sha = hashlib.sha256(payload).hexdigest()
    derived = folder / f"{sha}.mp4"
    derived.write_bytes(payload)
    return {
        "schema": SCHEMA,
        "original": {
            "path": str(clip.resolve()),
            "sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
            "size_bytes": clip.stat().st_size,
            "width": 640,
            "height": 360,
            "frame_rate": "30/1",
        },
        "derived": {
            "path": str(derived),
            "sha256": sha,
            "size_bytes": len(payload),
            "frames": frames,
            "width": 640,
            "height": 360,
            "frame_rate": "30/1",
        },
        "settings": {"start_frame": start, "end_frame": None, "fps_conversion": conversion},
        "contract": {
            "workflow_id": workflow_id,
            "workflow_version": version,
            "output_frames": frames,
            "output_fps": 24,
            "runtime_revision": "6b747c0428c343e1417219641db93a4fb7cb69ae",
            "consumption_rule": "rule",
        },
        "plan": {"source_indices": list(range(start, start + frames)), "window_frames": 100},
        "processing": {"tool": "ffmpeg", "lossless": True},
    }


def _form(clip: Path, record: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_RUNTIME_VERSION,
        "prompt": "A person in a studio, camera locked",
        "negative_prompt": "",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "seed": "424242",
        "frame_count": "41",
        "operator_controls": {"pose_prompt": "waves", "pose_strength": "1"},
    }
    if record is not None:
        form[PREPARED_MOTION_SOURCE_FIELD] = record
    form.update(overrides)
    return form


def _submit(controller, service, source, form):
    controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    [njr] = service.calls[-1]
    return njr


# --------------------------------------------------------------------- the prepared job


def test_a_prepared_motion_source_is_what_the_job_freezes_with_both_identities(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    form = _form(clip, record)
    before = copy.deepcopy(form)

    njr = _submit(controller, service, source, form)

    config = njr.config["video_workflow"]
    # What executes is the derived, content-addressed clip ...
    assert config["pose_video_path"] == record["derived"]["path"]
    assert config["pose_video_sha256"] == record["derived"]["sha256"]
    # ... and the record keeps where it came from and how it was made.
    frozen = config["motion_source_preparation"]
    assert frozen == record and frozen is not record
    assert frozen["original"]["sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert frozen["derived"]["sha256"] != frozen["original"]["sha256"]
    assert frozen["settings"] == {"start_frame": 7, "end_frame": None, "fps_conversion": "none"}
    assert frozen["processing"]["tool"] == "ffmpeg"
    metadata = njr.extra_metadata["video_workflow"]
    assert metadata["pose_video"] == {
        "path": record["derived"]["path"],
        "sha256": record["derived"]["sha256"],
    }
    assert metadata["motion_source_preparation"] == {
        "original": {"path": record["original"]["path"], "sha256": record["original"]["sha256"]},
        "derived": {"path": record["derived"]["path"], "sha256": record["derived"]["sha256"]},
        "settings": record["settings"],
    }
    # The form the caller passed in is not changed, and the job is a normal single submission.
    projection = form.pop("_stable_new_submission_projection")
    assert projection["frame_count"] == 41 and form == before
    assert len(service.calls) == 1


def test_the_compiler_binds_the_derived_clip_to_the_workflows_driving_input(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    njr = _submit(controller, service, source, _form(clip, record))
    spec = controller._njr_builder.spec_for(_form(clip))
    stage = dict(njr.config["video_workflow"])

    compiled = WorkflowCompiler().compile(
        spec,
        VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config=stage,
            output_dir=tmp_path,
            input_image_path=Path(njr.input_image_paths[0]),
            prompt=stage["prompt"],
            negative_prompt=stage["negative_prompt"],
            job_id=njr.job_id,
        ),
    )
    assert compiled.compiled_inputs["pose_video"] == record["derived"]["path"]
    assert compiled.compiled_inputs["frame_count"] == 41
    load_video = next(
        node
        for node in compiled.backend_payload["prompt"].values()
        if node["class_type"] == "LoadVideo"
    )
    assert load_video["inputs"]["file"] == record["derived"]["path"]


def test_dispatch_and_replay_reverify_the_derived_bytes(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    njr = _submit(controller, service, source, _form(clip, record))
    stage = njr.config["video_workflow"]
    derived = Path(record["derived"]["path"])

    # Dispatch (backend) and replay (frozen_input_checks) look at the derived clip ...
    ComfyWorkflowVideoBackend._verify_driving_video_source(
        stage["pose_video_path"], stage["pose_video_sha256"]
    )
    checks = [check for check in frozen_input_checks(njr) if check.label == "driving video"]
    assert [(c.path, c.expected_sha256) for c in checks] == [
        (record["derived"]["path"], record["derived"]["sha256"])
    ]
    assert verify_inputs(checks) == []
    # ... and the original being edited later does not matter to a job that no longer reads it.
    clip.write_bytes(b"edited later")
    assert verify_inputs(checks) == []

    derived.write_bytes(derived.read_bytes() + b"!")
    with pytest.raises(ValueError, match="changed since queue admission"):
        ComfyWorkflowVideoBackend._verify_driving_video_source(
            stage["pose_video_path"], stage["pose_video_sha256"]
        )
    [issue] = verify_inputs(checks)
    assert issue.reason == "changed since the job was created"


# --------------------------------------------------------------------- the default is unchanged


LEGACY_VIDEO_WORKFLOW_KEYS = {
    "enabled",
    "workflow_id",
    "workflow_version",
    "backend_id",
    "prompt",
    "negative_prompt",
    "video_execution",
    "seed",
    "frame_count",
    "fps",
    "operator_controls",
    "pose_video_path",
    "pose_video_sha256",
    "source_preparation",
}


def _frozen(njr: Any) -> dict[str, Any]:
    return {
        "config": copy.deepcopy(njr.config),
        "extra_metadata": copy.deepcopy(njr.extra_metadata),
        "input_image_paths": tuple(njr.input_image_paths),
    }


def test_an_unprepared_job_is_exactly_what_it_always_was(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)

    first = _submit(controller, service, source, _form(clip))
    second = _submit(controller, service, source, _form(clip))
    explicit_none = _submit(
        controller, service, source, _form(clip, PREPARED_MOTION_SOURCE_FIELD=None)
    )

    config = first.config["video_workflow"]
    assert set(config) == LEGACY_VIDEO_WORKFLOW_KEYS
    assert config["pose_video_path"] == str(clip.resolve())  # the original clip, by path and hash
    assert config["pose_video_sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert "motion_source_preparation" not in first.extra_metadata["video_workflow"]
    for other in (second, explicit_none):
        assert _frozen(first) == _frozen(other)
    assert not (tmp_path / "output" / "prepared_driving_videos").exists()  # nothing was prepared


def test_a_workflow_that_takes_no_driving_video_never_receives_one(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    form = _form(clip, workflow_id=PROMPT_ID, operator_controls={}, pose_video_path="")
    njr = _submit(controller, service, source, form)
    assert "pose_video_path" not in njr.config["video_workflow"]
    assert "motion_source_preparation" not in njr.config["video_workflow"]


# --------------------------------------------------------------------- nothing stale is accepted


def _edit_original(clip, record):
    clip.write_bytes(clip.read_bytes() + b" edited")


def _edit_derived(clip, record):
    Path(record["derived"]["path"]).write_bytes(b"swapped bytes")


def _delete_derived(clip, record):
    Path(record["derived"]["path"]).unlink()


def _delete_original(clip, record):
    clip.unlink()


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (_edit_original, "driving video changed since it was prepared"),
        (_edit_derived, "prepared motion source changed since it was prepared"),
        (_delete_derived, "no longer readable"),
    ],
)
def test_changed_or_missing_bytes_refuse_the_submission_before_anything_is_written(
    tmp_path, tamper, message
):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    tamper(clip, record)

    with pytest.raises(ValueError, match=message):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, record)
        )
    assert service.calls == []  # no job was admitted
    assert not (tmp_path / "output" / "prepared_video_sources").exists()  # not even the source PNG


def test_a_record_for_another_clip_workflow_version_or_length_is_refused(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    other_clip = tmp_path / "other.mp4"
    other_clip.write_bytes(b"another clip")
    record = _record(tmp_path, clip)

    cases = [
        (_form(other_clip, record), "different driving video"),
        (_form(clip, record, frame_count="49"), "output frames 41"),
        (_form(clip, record, workflow_version="1.1.0"), "workflow version"),
        (_form(clip, _record(tmp_path, clip, frames=49), frame_count="41"), "output frames 49"),
        (_form(clip, {**record, "schema": "something-else"}), "not recognised"),
        (_form(clip, {"schema": SCHEMA}), "incomplete"),
    ]
    for form, message in cases:
        with pytest.raises(ValueError, match=message):
            controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    assert service.calls == []


def test_a_record_without_a_driving_video_or_for_a_workflow_without_one_is_refused(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    with pytest.raises(ValueError, match="does not accept the requested pose video"):
        controller.submit_video_workflow_job(
            source_image_path=source,
            form_data=_form(clip, record, workflow_id=PROMPT_ID, operator_controls={}),
        )
    with pytest.raises(ValueError, match="needs a driving video"):  # the form check comes first
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, record, pose_video_path="")
        )
    # The freezing step refuses on its own too, whoever calls it.
    with pytest.raises(ValueError, match="takes a driving video"):
        controller._njr_builder.freeze_shared_inputs(_form(clip, record, pose_video_path=""))
    assert service.calls == []


# --------------------------------------------------------------------- batch and experiment


def _batch_sources(tmp_path: Path, count: int = 2) -> list[str]:
    paths = []
    for index in range(count):
        path = tmp_path / f"src_{index}.png"
        Image.new("RGB", (600 + 10 * index, 900), (index * 40, 120, 200)).save(path)
        paths.append(str(path))
    return paths


def test_a_batch_shares_one_prepared_clip_and_stays_all_or_none(tmp_path):
    controller, service = _stack(tmp_path)
    _source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    selection = controller.select_batch_sources(_batch_sources(tmp_path, 3))

    plan = controller.preview_batch(sources=selection.sources, form_data=_form(clip, record))
    assert plan.eligible, plan.assessment.problems
    stages = [njr.config["video_workflow"] for njr in plan.njrs]
    assert {stage["pose_video_path"] for stage in stages} == {record["derived"]["path"]}
    assert all(stage["motion_source_preparation"]["original"]["sha256"] for stage in stages)

    # Editing the derived clip OR the original between preview and admission refuses every job.
    derived = Path(record["derived"]["path"])
    good = derived.read_bytes()
    derived.write_bytes(b"tampered")
    with pytest.raises(BatchRefused, match="changed after it was frozen"):
        controller.submit_batch(plan)
    derived.write_bytes(good)
    clip.write_bytes(clip.read_bytes() + b" edited")
    with pytest.raises(BatchRefused, match="original driving video changed after it was frozen"):
        controller.submit_batch(plan)
    assert service.calls == []

    clip.write_bytes(clip.read_bytes()[: -len(b" edited")])
    result = controller.submit_batch(plan)
    assert len(service.calls) == 1 and len(service.calls[0]) == 3  # one admission, every job
    assert len(result.job_ids) == 3


def test_a_stale_record_blocks_the_whole_batch_preview(tmp_path):
    controller, _service = _stack(tmp_path)
    _source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    clip.write_bytes(b"replaced before the preview")
    selection = controller.select_batch_sources(_batch_sources(tmp_path, 2))
    plan = controller.preview_batch(sources=selection.sources, form_data=_form(clip, record))
    assert not plan.eligible and "changed since it was prepared" in plan.assessment.form_error


def test_one_variable_experiment_arms_share_the_prepared_clip_and_reverify_it(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip)
    form = _form(clip, record)

    plan = controller.preview_experiment(
        source_image_path=source, form_data=form, variable_name="pose_strength", candidates=["0.8"]
    )
    assert len(plan.arms) == 2
    assert {arm.njr.config["video_workflow"]["pose_video_path"] for arm in plan.arms} == {
        record["derived"]["path"]
    }
    Path(record["derived"]["path"]).write_bytes(b"tampered")
    with pytest.raises(ExperimentRefused, match="changed after it was frozen"):
        controller.submit_experiment(plan)
    assert service.calls == []


# --------------------------------------------------------------------- end to end with FFmpeg


def _make_clip(tmp_path: Path, frames: int = 90) -> Path:
    path = tmp_path / "real.mp4"
    subprocess.run(
        [str(resolve_ffmpeg_executable()), "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=64x48:rate=30", "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return path


def _decoded(path: Path) -> list[str]:
    result = subprocess.run(
        [str(resolve_ffmpeg_executable()), "-v", "error", "-nostdin", "-noautorotate", "-i",
         str(path), "-an", "-fps_mode", "passthrough", "-pix_fmt", "yuv420p", "-f", "framemd5", "-"],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in result.stdout.decode().splitlines()
        if line and not line.startswith("#")
    ]


@needs_ffmpeg
def test_the_previewed_source_and_the_frozen_submission_source_are_the_same_file(tmp_path):
    controller, service = _stack(tmp_path)
    source, _ = _inputs(tmp_path)
    clip = _make_clip(tmp_path)
    form = _form(clip)

    outcome = controller.prepare_motion_source(
        form, {"start": 12, "unit": "frames", "fps_conversion": "workflow_rate"}, None
    )
    assert outcome.prepared, outcome.message
    form[PREPARED_MOTION_SOURCE_FIELD] = outcome.record
    njr = _submit(controller, service, source, form)
    stage = njr.config["video_workflow"]

    # Agreement, by path, by bytes and by decoded content.
    assert outcome.preview.path == stage["pose_video_path"] == outcome.record["derived"]["path"]
    frozen_bytes = hashlib.sha256(Path(stage["pose_video_path"]).read_bytes()).hexdigest()
    assert frozen_bytes == stage["pose_video_sha256"] == outcome.record["derived"]["sha256"]
    source_frames = _decoded(clip)
    assert _decoded(Path(stage["pose_video_path"])) == [
        source_frames[index] for index in outcome.plan.source_indices
    ]
    assert stage["motion_source_preparation"]["plan"]["source_indices"] == list(
        outcome.plan.source_indices
    )
    assert len(outcome.plan.source_indices) == njr.config["video_workflow"]["frame_count"] == 41


@needs_ffmpeg
def test_a_cancelled_or_failed_preparation_has_no_record_and_so_no_prepared_job(tmp_path):
    controller, service = _stack(tmp_path)
    clip = _make_clip(tmp_path)
    cancelled = threading.Event()
    cancelled.set()
    outcome = controller.prepare_motion_source(
        _form(clip), {"start": 0, "unit": "frames"}, cancelled
    )
    assert outcome.status == "cancelled" and outcome.record is None
    failed = controller.prepare_motion_source(_form(clip), {"start": 5000, "unit": "frames"}, None)
    assert failed.status == "failed" and failed.record is None
    assert not (tmp_path / "output" / "prepared_driving_videos").exists() or not list(
        (tmp_path / "output" / "prepared_driving_videos").glob("*.mp4")
    )
    assert service.calls == []  # preparing alone never admits anything


# --------------------------------------------------------------------- structure


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_preparation_stays_below_the_controller_and_apart_from_the_advisories():
    root = Path(__file__).resolve().parents[2] / "src" / "video"
    forbidden = re.compile(
        r"^src\.(gui|queue|controller|history|learning|pipeline\.(job_models_v2|njr_core_v26|"
        r"reprocess_builder|pipeline_runner))"
    )
    advisories = {"src.video.motion_source_readiness", "src.video.workflow_motion_guidance"}
    for name in (
        "motion_source_plan.py",
        "motion_source_preparation.py",
        "driving_frame_consumption.py",
    ):
        imports = _imports(root / name)
        assert [module for module in imports if forbidden.match(module)] == [], name
        assert not imports & advisories, name  # the job-affecting path never reads an advisory
    # The only new thing the builder imports is the verifier and the contract, not the advisories.
    builder = _imports(root / "video_workflow_njr_builder.py")
    assert {"src.video.motion_source_plan", "src.video.motion_source_preparation"} <= builder
    assert not builder & advisories
    assert "src.video.driving_video_inspection" not in builder  # reached only through preparation


def test_no_new_queue_runner_or_history_authority_is_introduced():
    root = Path(__file__).resolve().parents[2] / "src" / "video"
    for name in ("motion_source_plan.py", "motion_source_preparation.py"):
        text = (root / name).read_text(encoding="utf-8")
        for token in ("submit_njrs", "JobService", "run_njr", "JobRepository", "PipelineRunner"):
            assert token not in text, (name, token)
