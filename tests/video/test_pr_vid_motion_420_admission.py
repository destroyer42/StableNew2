"""PR-VID-MOTION-420: an aligned clip is verified, frozen and re-verified through the one production path.

Drives the real Video Workflow controller with a fake JobService: nothing is generated, no runtime starts.
The aligned records are produced by real FFmpeg on disposable clips (skipped without FFmpeg); the refusal cases
tamper with those real files and records.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.motion_alignment import AlignmentIntent
from src.video.motion_alignment_preparation import (
    ALIGNED_SCHEMA,
    AlignedPreparationError,
    prepare_aligned_for_form,
    validate_aligned_record,
    verify_aligned_dispatch,
)
from src.video.motion_alignment_support import (
    alignment_support,
    comfy_center_crop_offsets,
    resize_is_spatially_inert,
)
from src.video.video_workflow_njr_builder import PREPARED_MOTION_SOURCE_FIELD
from src.video.workflow_catalog_fun_control import FUN_ID
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from src.video.workflow_registry import build_default_workflow_registry
from tests.video.motion_420_support import moving_square_clip, needs_ffmpeg

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


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


def _source(tmp_path: Path, name: str = "portrait.png", color=(20, 120, 200)) -> Path:
    path = tmp_path / name
    Image.new("RGB", (600, 900), color).save(path)
    return path


def _form(
    clip: Path, source: Path, record: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_RUNTIME_VERSION,
        "prompt": "A person in a studio, camera locked",
        "negative_prompt": "",
        "pose_video_path": str(clip),
        "source_image_path": str(source),
        "experimental_opt_in": True,
        "seed": "424242",
        "frame_count": "17",
        "operator_controls": {"pose_prompt": "waves", "pose_strength": "1"},
    }
    if record is not None:
        form[PREPARED_MOTION_SOURCE_FIELD] = record
    form.update(overrides)
    return form


def _aligned(
    controller, form: dict[str, Any], intent: AlignmentIntent, tmp_path: Path
) -> dict[str, Any]:
    spec = controller._njr_builder.spec_for(form)
    outcome = prepare_aligned_for_form(
        spec,
        form,
        {"intent": intent, "start": 0, "end": None, "unit": "frames", "fps_conversion": "none"},
        controller._njr_builder.output_dir(),
    )
    assert outcome.prepared, (outcome.code, outcome.message)
    return outcome.record


def _submit(controller, service, source, form):
    controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    [njr] = service.calls[-1]
    return njr


@pytest.fixture
def world(tmp_path: Path):
    controller, service = _stack(tmp_path)
    clip = moving_square_clip(tmp_path)
    source = _source(tmp_path)
    return controller, service, clip, source, tmp_path


# ------------------------------------------------------------------------------ support declaration


def test_support_is_decided_from_the_declared_graph_not_from_a_driving_field():
    registry = build_default_workflow_registry()
    drive = registry.get(
        WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION, allow_experimental=True
    )
    support = alignment_support(drive)
    assert support.supported and "only spatial step" in support.resize_statement
    ti2v = next(s for s in registry.list_specs_for_backend("comfy") if s.workflow_id == TI2V_ID)
    assert alignment_support(ti2v).supported is False
    prompt_mode = registry.get(
        "wan_animate2_prompt_i2v_v1", WAN_ANIMATE2_RUNTIME_VERSION, allow_experimental=True
    )
    assert not alignment_support(prompt_mode).supported
    for version in ("1.0.0", "1.1.0"):
        fun = registry.get(FUN_ID, version, allow_experimental=True)
        assert not alignment_support(fun).supported
        assert "edges" in alignment_support(fun).reason
    # a graph whose resize is not the verified one is refused, whatever its declared inputs say
    altered = copy.deepcopy(drive)
    template = altered.backend_defaults["prompt_template"]
    node = next(n for n in template.values() if n.get("class_type") == "ResizeImageMaskNode")
    node["inputs"]["resize_type.crop"] = "disabled"
    assert not alignment_support(altered).supported


def test_the_workflows_own_resize_is_the_identity_at_the_frozen_target_size():
    for size in ((480, 832), (832, 480), (479, 831)):
        assert comfy_center_crop_offsets(*size, *size) == (0, 0)
        assert resize_is_spatially_inert(*size, *size)
    assert not resize_is_spatially_inert(1080, 1920, 480, 832)
    assert (
        comfy_center_crop_offsets(1920, 1080, 480, 832)[0] > 0
    )  # an unaligned clip is cropped by the graph


# ------------------------------------------------------------------------------ admission


@needs_ffmpeg
def test_an_aligned_clip_is_what_the_job_freezes_beside_the_unchanged_original(world):
    controller, service, clip, source, tmp_path = world
    form = _form(clip, source)
    record = _aligned(controller, form, AlignmentIntent(scale=0.9, translate_x=10), tmp_path)
    before = copy.deepcopy(record)
    njr = _submit(controller, service, source, _form(clip, source, record))

    config = njr.config["video_workflow"]
    assert config["pose_video_path"] == record["derived"]["path"]
    assert config["pose_video_sha256"] == record["derived"]["sha256"]
    frozen = config["motion_source_preparation"]
    assert frozen == record == before and frozen is not record
    assert frozen["schema"] == ALIGNED_SCHEMA
    assert frozen["original"]["sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert (
        frozen["original"]["sha256"] != frozen["derived"]["sha256"]
    )  # asset identity != derivative identity
    assert config["source_preparation"]["prepared_dimensions"] == {"width": 480, "height": 832}
    metadata = njr.extra_metadata["video_workflow"]["motion_source_preparation"]
    assert metadata["alignment"]["transform_sha256"] == record["alignment"]["transform_sha256"]
    assert (
        metadata["alignment"]["mirror"] is False
        and metadata["original"]["sha256"] == frozen["original"]["sha256"]
    )
    assert len(service.calls) == 1  # one normal admission, nothing else was queued


@needs_ffmpeg
def test_a_motion_library_binding_stays_on_the_original_asset(world):
    controller, service, clip, source, tmp_path = world
    form = _form(clip, source)
    record = _aligned(controller, form, AlignmentIntent(scale=0.9), tmp_path)
    original_sha = record["original"]["sha256"]
    binding = {"asset_id": "mlib_" + "a" * 16, "sha256": original_sha}
    njr = _submit(
        controller, service, source, _form(clip, source, record, motion_library_asset=binding)
    )
    assert njr.extra_metadata["video_workflow"]["motion_library_asset"] == binding
    assert njr.config["video_workflow"]["pose_video_sha256"] != original_sha
    bad = {
        "asset_id": "mlib_" + "a" * 16,
        "sha256": record["derived"]["sha256"],
    }  # the derivative is not the asset
    with pytest.raises(ValueError, match="no longer matches the Motion Library clip"):
        controller.submit_video_workflow_job(
            source_image_path=source,
            form_data=_form(clip, source, record, motion_library_asset=bad),
        )


@needs_ffmpeg
def test_an_aligned_clip_belongs_to_exactly_one_source_image(world):
    controller, service, clip, source, tmp_path = world
    record = _aligned(controller, _form(clip, source), AlignmentIntent(scale=0.9), tmp_path)
    other = _source(tmp_path, "other.png", color=(200, 20, 20))
    with pytest.raises(ValueError, match="different source image"):
        controller.submit_video_workflow_job(
            source_image_path=other, form_data=_form(clip, other, record)
        )
    assert service.calls == []  # refused before anything was built or queued
    source.write_bytes(source.read_bytes() + b"\x00")  # the same file changed after alignment
    with pytest.raises(ValueError, match="different source image|changed"):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, source, record)
        )
    assert service.calls == []


@needs_ffmpeg
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"frame_count": "21"}, "length|output frames|aligned for"),
        ({"workflow_version": "1.1.0"}, "workflow version|aligned for"),
    ],
)
def test_a_changed_workflow_version_or_length_requires_aligning_again(world, change, message):
    controller, service, clip, source, tmp_path = world
    record = _aligned(controller, _form(clip, source), AlignmentIntent(scale=0.9), tmp_path)
    with pytest.raises(ValueError, match=message):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, source, record, **change)
        )
    assert service.calls == []


@needs_ffmpeg
def test_a_changed_driving_clip_or_derivative_is_refused(world):
    controller, service, clip, source, tmp_path = world
    record = _aligned(controller, _form(clip, source), AlignmentIntent(scale=0.9), tmp_path)
    derived = Path(record["derived"]["path"])
    derived.write_bytes(derived.read_bytes() + b"!")
    with pytest.raises(ValueError, match="changed since it was aligned"):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, source, record)
        )
    derived.write_bytes(derived.read_bytes()[:-1])
    other_clip = moving_square_clip(tmp_path, "other_driver.mp4", step=(2, 0))
    with pytest.raises(ValueError, match="different driving video"):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(other_clip, source, record)
        )
    clip.write_bytes(clip.read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="driving video changed since it was aligned"):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, source, record)
        )
    assert service.calls == []


@needs_ffmpeg
@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r["alignment"].__setitem__("scale", 1.2),
        lambda r: r["alignment"].__setitem__("mirror", True),
        lambda r: r["alignment"].__setitem__(
            "transform_version", "stablenew.alignment-transform.v0"
        ),
        lambda r: r["alignment"].__setitem__("driver_original_sha256", "0" * 64),
        lambda r: r["plan"]["source_indices"].reverse(),
        lambda r: r["derived"].__setitem__("width", 481),
    ],
)
def test_a_hand_edited_or_recomputed_record_is_never_trusted(world, edit):
    controller, service, clip, source, tmp_path = world
    record = _aligned(controller, _form(clip, source), AlignmentIntent(scale=0.9), tmp_path)
    edited = copy.deepcopy(record)
    edit(edited)
    with pytest.raises(ValueError):
        controller.submit_video_workflow_job(
            source_image_path=source, form_data=_form(clip, source, edited)
        )
    assert service.calls == []


@needs_ffmpeg
def test_a_workflow_that_cannot_take_alignment_refuses_an_aligned_record(world):
    controller, service, clip, source, tmp_path = world
    record = _aligned(controller, _form(clip, source), AlignmentIntent(scale=0.9), tmp_path)
    form = _form(clip, source, record, workflow_id=FUN_ID, workflow_version="1.1.0")
    with pytest.raises(ValueError):
        controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    ti2v = _form(
        clip, source, record, workflow_id=TI2V_ID, workflow_version="", operator_controls={}
    )
    with pytest.raises(ValueError):
        controller.submit_video_workflow_job(source_image_path=source, form_data=ti2v)
    assert service.calls == []


def test_preparation_is_refused_up_front_for_a_workflow_that_cannot_take_it(tmp_path):
    controller, _service = _stack(tmp_path)
    clip, source = tmp_path / "c.mp4", _source(tmp_path)
    clip.write_bytes(b"x")
    form = _form(clip, source, workflow_id=FUN_ID, workflow_version="1.1.0")
    spec = controller._njr_builder.spec_for(form)
    outcome = prepare_aligned_for_form(spec, form, {"intent": AlignmentIntent()}, tmp_path / "out")
    assert outcome.code == "unavailable" and "edges" in outcome.message
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------------------ dispatch and replay


@needs_ffmpeg
def test_dispatch_and_replay_reverify_the_frozen_aligned_artifacts(world):
    controller, service, clip, source, tmp_path = world
    record = _aligned(
        controller, _form(clip, source), AlignmentIntent(scale=0.9, translate_y=8), tmp_path
    )
    njr = _submit(controller, service, source, _form(clip, source, record))
    stage = njr.config["video_workflow"]
    reference = njr.input_image_paths[0]

    ComfyWorkflowVideoBackend._verify_driving_video_source(
        stage["pose_video_path"], stage["pose_video_sha256"]
    )
    verify_aligned_dispatch(stage, reference)  # the aligned contract holds at execution

    checks = [c for c in frozen_input_checks(njr) if c.label == "driving video"]
    assert [(c.path, c.expected_sha256) for c in checks] == [
        (record["derived"]["path"], record["derived"]["sha256"])
    ]
    assert verify_inputs(checks) == []
    clip.write_bytes(b"edited later")  # the original is not read by a job that froze the derivative
    assert verify_inputs(checks) == []
    verify_aligned_dispatch(stage, reference)

    tampered = copy.deepcopy(stage)
    tampered["motion_source_preparation"]["alignment"]["scale"] = 1.3
    with pytest.raises(AlignedPreparationError):
        verify_aligned_dispatch(tampered, reference)
    swapped = copy.deepcopy(stage)
    swapped["pose_video_sha256"] = "f" * 64
    with pytest.raises(AlignedPreparationError, match="frozen driving video"):
        verify_aligned_dispatch(swapped, reference)
    other_ref = tmp_path / "other_ref.png"
    Image.new("RGB", (480, 832), (1, 2, 3)).save(other_ref)
    with pytest.raises(AlignedPreparationError, match="reference image"):
        verify_aligned_dispatch(stage, other_ref)
    with pytest.raises(AlignedPreparationError, match="no reference image"):
        verify_aligned_dispatch(stage, None)  # fail closed: never run an aligned clip unverified

    Path(record["derived"]["path"]).write_bytes(b"gone wrong")
    [issue] = verify_inputs(checks)
    assert issue.reason == "changed since the job was created"
    Path(record["derived"]["path"]).unlink()
    [missing] = verify_inputs(checks)
    assert "missing" in missing.reason


@needs_ffmpeg
def test_replay_never_recomputes_the_alignment_from_current_settings(world):
    controller, service, clip, source, tmp_path = world
    record = _aligned(
        controller, _form(clip, source), AlignmentIntent(scale=0.9, translate_x=20), tmp_path
    )
    njr = _submit(controller, service, source, _form(clip, source, record))
    stage = copy.deepcopy(njr.config["video_workflow"])
    # An older record keeps its own recorded transform version; a newer algorithm would not be applied silently.
    stage["motion_source_preparation"]["alignment"]["transform_version"] = (
        "stablenew.alignment-transform.v2"
    )
    with pytest.raises(AlignedPreparationError, match="different transform version"):
        verify_aligned_dispatch(stage, njr.input_image_paths[0])


@needs_ffmpeg
def test_historical_unprepared_and_plain_prepared_jobs_are_untouched(world):
    controller, service, clip, source, tmp_path = world
    plain = _submit(controller, service, source, _form(clip, source))
    config = plain.config["video_workflow"]
    assert "motion_source_preparation" not in config
    assert config["pose_video_path"] == str(clip.resolve())
    assert "alignment" not in plain.extra_metadata["video_workflow"].get(
        "motion_source_preparation", {}
    )
    verify_aligned_dispatch(
        config, plain.input_image_paths[0]
    )  # a no-op for anything that is not aligned
    assert validate_aligned_record is not None


def test_nothing_in_admission_imports_the_advisory_or_gui_layers():
    import ast

    import src.video.motion_alignment_preparation as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name.startswith(("src.gui", "src.queue", "src.controller")) for name in imported)
    assert "src.video.motion_alignment_compatibility" not in imported
    assert "src.video.motion_source_readiness" not in imported
