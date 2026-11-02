"""PR-VID-MOTION-LIB-353: History import, the driving-video handoff and the canonical admission path.

The production ``VideoWorkflowController`` runs over a fake ``JobService`` (so nothing can really queue) and a
real temporary SQLite repository for History.  Clips are placeholder files with a scripted inspector, or tiny
CPU-only FFmpeg clips where a test needs a real probe.  No runtime, model, GPU or network is started.
"""

from __future__ import annotations

import copy
import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.queue.job_model import JobStatus
from src.video.motion_library.handoff import (
    FIELD_DRIVING_VIDEO,
    binding_for_submission,
    plan_driving_handoff,
)
from src.video.motion_library.importer import (
    OUTCOME_DUPLICATE,
    OUTCOME_FAILED,
    OUTCOME_IMPORTED,
    import_history_video,
    import_video,
)
from src.video.motion_library.models import SOURCE_OWNER_RECORDED, SOURCE_STABLENEW_GENERATED
from src.video.video_workflow_njr_builder import (
    MOTION_LIBRARY_ASSET_FIELD,
    PREPARED_MOTION_SOURCE_FIELD,
)
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from tests.helpers.make_video_313 import TI2V_ID, make_app, make_image
from tests.helpers.motion_library_353 import (
    FakeInspector,
    make_clip,
    needs_ffmpeg,
    new_store,
    write_clip,
)
from tests.helpers.video_review_211 import finish, new_repository, persist, video_result


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


def _portrait(tmp_path: Path) -> Path:
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    return source


def _form(clip: Path, **overrides: Any) -> dict[str, Any]:
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
    form.update(overrides)
    return form


def _meta(controller: VideoWorkflowController, workflow_id: str) -> dict[str, Any]:
    return next(s for s in controller.list_workflow_specs() if s["workflow_id"] == workflow_id)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- History import -------------------------------------------------------------------------------


def _completed_job(tmp_path: Path, name: str = "alpha", seed: str = "5"):
    app, controller, service = make_app(tmp_path)
    source = make_image(tmp_path / f"{name}.png")
    controller.submit_video_workflow_job(
        source_image_path=source,
        form_data={
            "workflow_id": TI2V_ID,
            "workflow_version": "1.2.0",
            "prompt": f"{name} turns around",
            "seed": seed,
        },
    )
    repository = new_repository(tmp_path, f"{name}.sqlite3")
    [job_id] = persist(repository, [service.submitted[-1]])
    return repository, job_id, source


def _clip_for(tmp_path: Path, name: str = "alpha") -> Path:
    return write_clip(tmp_path / "output" / f"{name}.mp4", f"generated {name}".encode())


def test_a_completed_history_video_is_cataloged_with_its_job_provenance(tmp_path: Path) -> None:
    repository, job_id, source = _completed_job(tmp_path)
    clip = _clip_for(tmp_path)
    finish(repository, job_id, JobStatus.COMPLETED, result=video_result(clip))
    store = new_store(tmp_path)

    outcome = import_history_video(
        store,
        repository.get_job(job_id),
        motion_label="turn around",
        motion_achieved=True,
        good_for_motion=True,
        known_artifacts="hand flicker",
        reuse_conditions="front view only",
        inspect=FakeInspector(),
    )

    assert outcome.status == OUTCOME_IMPORTED
    asset = store.require(outcome.asset_id)
    assert asset.source_category == SOURCE_STABLENEW_GENERATED and asset.is_generated
    assert asset.display_name == "turn around" and asset.good_for_motion is True
    origin = asset.origin
    assert origin is not None
    assert (origin.job_id, origin.seed, origin.workflow_id) == (job_id, 5, TI2V_ID)
    assert origin.workflow_version == "1.2.0" and origin.backend_id == "comfy"
    assert origin.artifact_sha256 == asset.sha256 == _sha(clip)
    assert origin.source_image_path == str(Path(source))
    assert "alpha turns around" in origin.prompt
    assert origin.motion_achieved is True and origin.motion_label == "turn around"
    assert origin.known_artifacts == "hand flicker" and origin.reuse_conditions == "front view only"
    assert clip.exists()  # a reference, never a move or copy of the job's artifact
    assert not store.managed_dir.exists()
    # The provenance survives a restart and the operator may later change the judged fields.
    reopened = type(store)(store.root)
    reopened.update_origin(
        asset.asset_id, {"motion_achieved": False, "known_artifacts": "ghosting"}
    )
    assert reopened.require(asset.asset_id).origin.motion_achieved is False
    assert reopened.require(asset.asset_id).origin.job_id == job_id


@pytest.mark.parametrize(
    ("status", "result", "fragment"),
    [
        (JobStatus.RUNNING, None, "completed"),
        (JobStatus.FAILED, {"error": "boom"}, "completed"),
        (JobStatus.COMPLETED, {"success": True}, "no video"),
        (JobStatus.COMPLETED, {"error": "x", "video_bundle": {"primary_path": "a.mp4"}}, "error"),
    ],
)
def test_ineligible_history_jobs_are_refused_with_a_reason(
    tmp_path, status, result, fragment
) -> None:
    repository, job_id, _ = _completed_job(tmp_path)
    if status is JobStatus.RUNNING:
        job = repository.get_job_model(job_id)
        repository.transition_job(job, JobStatus.RUNNING)
    else:
        finish(
            repository,
            job_id,
            status,
            result=result,
            error="boom" if status is JobStatus.FAILED else None,
        )
    store = new_store(tmp_path)

    outcome = import_history_video(store, repository.get_job(job_id), inspect=FakeInspector())

    assert outcome.status == OUTCOME_FAILED and fragment in outcome.reason.lower()
    assert len(store) == 0


def test_missing_ambiguous_and_mismatched_history_artifacts_are_refused(tmp_path: Path) -> None:
    repository, job_id, _ = _completed_job(tmp_path)
    gone = tmp_path / "output" / "gone.mp4"
    finish(repository, job_id, JobStatus.COMPLETED, result=video_result(gone))
    store = new_store(tmp_path)
    inspector = FakeInspector()

    missing = import_history_video(store, repository.get_job(job_id), inspect=inspector)
    assert missing.status == OUTCOME_FAILED and "missing or was moved" in missing.reason

    assert (
        import_history_video(store, None, inspect=inspector).reason
        == "That job was not found in History."
    )

    first, second = _clip_for(tmp_path, "one"), _clip_for(tmp_path, "two")
    entry = repository.get_job(job_id)
    entry.result["video_bundle"] = {"video_paths": [str(first), str(second)], "backend_id": "comfy"}
    ambiguous = import_history_video(store, entry, inspect=inspector)
    assert ambiguous.status == OUTCOME_FAILED and "several videos" in ambiguous.reason

    entry.result["video_bundle"] = {
        "primary_path": str(first),
        "video_paths": [str(first)],
        "sha256": "0" * 64,
    }
    mismatch = import_history_video(store, entry, inspect=inspector)
    assert mismatch.status == OUTCOME_FAILED and "SHA-256" in mismatch.reason

    entry.result["video_bundle"] = {"frame_paths": [str(first)], "backend_id": "comfy"}
    frames = import_history_video(store, entry, inspect=inspector)
    assert "frame sequence" in frames.reason
    assert inspector.calls == [] and len(store) == 0


def test_the_same_bytes_from_history_keep_one_asset_and_gain_the_job_origin(tmp_path: Path) -> None:
    repository, job_id, _ = _completed_job(tmp_path)
    clip = _clip_for(tmp_path)
    finish(repository, job_id, JobStatus.COMPLETED, result=video_result(clip))
    store = new_store(tmp_path)
    owner = import_video(
        store,
        clip,
        annotations={"source_category": SOURCE_OWNER_RECORDED, "tags": "keep"},
        inspect=FakeInspector(),
    )

    again = import_history_video(store, repository.get_job(job_id), inspect=FakeInspector())

    assert again.status == OUTCOME_DUPLICATE and again.asset_id == owner.asset_id
    asset = store.require(owner.asset_id)
    assert (
        len(store) == 1 and asset.source_category == SOURCE_OWNER_RECORDED
    )  # the operator's label wins
    assert asset.origin is not None and asset.origin.job_id == job_id and asset.tags == ("keep",)


# --- handoff plan ---------------------------------------------------------------------------------


def _library_with(tmp_path: Path, **notes: Any):
    store = new_store(tmp_path)
    clip = write_clip(tmp_path / "in" / "driving.mp4")
    asset_id = import_video(store, clip, annotations=notes, inspect=FakeInspector()).asset_id
    return store, asset_id, clip


def test_a_verified_clip_populates_only_the_driving_video_field(tmp_path: Path) -> None:
    controller, _ = _stack(tmp_path)
    store, asset_id, clip = _library_with(tmp_path, review_status="reviewed")

    plan = plan_driving_handoff(store, asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))

    assert plan.ok and plan.refusal == ""
    assert plan.form_fields == {FIELD_DRIVING_VIDEO: str(clip.resolve())}
    assert plan.binding == {"asset_id": asset_id, "sha256": _sha(clip)}
    assert plan.workflow_id == WAN_ANIMATE2_DRIVE_ID
    text = " ".join(plan.advisories)
    assert "model-neutral" in text and "experimental" in text


def test_a_workflow_without_a_driving_input_is_refused_and_never_replaced(tmp_path: Path) -> None:
    controller, _ = _stack(tmp_path)
    store, asset_id, _ = _library_with(tmp_path)
    meta = _meta(controller, TI2V_ID)

    plan = plan_driving_handoff(store, asset_id, meta)

    assert not plan.ok and "does not take a driving video" in plan.refusal
    assert plan.form_fields == {} and plan.binding == {}
    assert (
        plan.workflow_id == TI2V_ID
    )  # the refusal names the selected workflow; none was chosen for you
    assert not plan_driving_handoff(store, asset_id, None).ok
    assert "No Video Workflow" in plan_driving_handoff(store, asset_id, {}).refusal
    assert "no longer exists" in plan_driving_handoff(store, "mlib_" + "0" * 32, meta).refusal


def test_missing_or_changed_files_fail_closed_with_a_corrective_action(tmp_path: Path) -> None:
    controller, _ = _stack(tmp_path)
    store, asset_id, clip = _library_with(tmp_path)
    meta = _meta(controller, WAN_ANIMATE2_DRIVE_ID)

    clip.write_bytes(clip.read_bytes() + b"tampered")
    changed = plan_driving_handoff(store, asset_id, meta)
    assert not changed.ok and "SHA-256" in changed.refusal and "Import" in changed.corrective_action

    clip.unlink()
    missing = plan_driving_handoff(store, asset_id, meta)
    assert (
        not missing.ok
        and "missing" in missing.refusal.lower()
        and "Relink" in missing.corrective_action
    )


def test_handoff_planning_queues_nothing_and_leaves_the_source_bytes_alone(tmp_path: Path) -> None:
    controller, service = _stack(tmp_path)
    store, asset_id, clip = _library_with(tmp_path)
    before = (clip.read_bytes(), clip.stat().st_mtime_ns)

    plan = plan_driving_handoff(store, asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))

    assert plan.ok and service.calls == []
    assert (clip.read_bytes(), clip.stat().st_mtime_ns) == before


def test_the_binding_applies_only_while_the_field_still_names_the_handed_over_file(
    tmp_path: Path,
) -> None:
    binding = {"asset_id": "mlib_" + "a" * 32, "sha256": "b" * 64}
    here = str(tmp_path / "a.mp4")
    assert binding_for_submission(binding, current_path=here, bound_path=here) == binding
    assert (
        binding_for_submission(binding, current_path=str(tmp_path / "b.mp4"), bound_path=here)
        is None
    )
    assert binding_for_submission(binding, current_path="", bound_path=here) is None
    assert binding_for_submission(None, current_path=here, bound_path=here) is None
    assert (
        binding_for_submission({"asset_id": "", "sha256": ""}, current_path=here, bound_path=here)
        is None
    )


# --- canonical admission --------------------------------------------------------------------------


def test_explicit_submission_goes_through_the_canonical_path_and_freezes_the_library_identity(
    tmp_path,
):
    controller, service = _stack(tmp_path)
    store, asset_id, clip = _library_with(tmp_path)
    plan = plan_driving_handoff(store, asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))
    form = _form(clip, **plan.form_fields, **{MOTION_LIBRARY_ASSET_FIELD: plan.binding})
    assert service.calls == []  # planning and filling the form queued nothing

    controller.submit_video_workflow_job(source_image_path=_portrait(tmp_path), form_data=form)

    [njr] = service.calls[-1]
    config = njr.config["video_workflow"]
    assert config["pose_video_sha256"] == _sha(clip)
    metadata = njr.extra_metadata["video_workflow"]
    assert metadata["motion_library_asset"] == {"asset_id": asset_id, "sha256": _sha(clip)}
    assert metadata["pose_video"]["sha256"] == _sha(clip)
    assert len(service.calls) == 1


def test_a_swapped_file_cannot_carry_a_library_identity_into_a_job(tmp_path):
    controller, service = _stack(tmp_path)
    store, asset_id, clip = _library_with(tmp_path)
    plan = plan_driving_handoff(store, asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 a different clip now")

    with pytest.raises(ValueError, match="no longer matches the Motion Library clip"):
        controller.submit_video_workflow_job(
            source_image_path=_portrait(tmp_path),
            form_data=_form(clip, **{MOTION_LIBRARY_ASSET_FIELD: plan.binding}),
        )
    assert service.calls == []


def test_a_job_without_a_library_binding_is_unchanged(tmp_path):
    controller, service = _stack(tmp_path)
    clip = write_clip(tmp_path / "driving.mp4")
    controller.submit_video_workflow_job(
        source_image_path=_portrait(tmp_path), form_data=_form(clip)
    )
    [njr] = service.calls[-1]
    assert "motion_library_asset" not in njr.extra_metadata["video_workflow"]


def test_a_prepared_source_keeps_the_original_library_identity_not_the_derived_clip(tmp_path):
    controller, service = _stack(tmp_path)
    store, asset_id, clip = _library_with(tmp_path)
    plan = plan_driving_handoff(store, asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))
    record = _prepared_record(tmp_path, clip)

    controller.submit_video_workflow_job(
        source_image_path=_portrait(tmp_path),
        form_data=_form(
            clip,
            **{
                MOTION_LIBRARY_ASSET_FIELD: plan.binding,
                PREPARED_MOTION_SOURCE_FIELD: copy.deepcopy(record),
            },
        ),
    )

    [njr] = service.calls[-1]
    metadata = njr.extra_metadata["video_workflow"]
    assert metadata["motion_library_asset"]["sha256"] == record["original"]["sha256"]
    assert metadata["pose_video"]["sha256"] == record["derived"]["sha256"] != _sha(clip)


def _prepared_record(tmp_path: Path, clip: Path) -> dict[str, Any]:
    from src.video.motion_source_plan import SCHEMA

    folder = tmp_path / "output" / "prepared_driving_videos"
    folder.mkdir(parents=True, exist_ok=True)
    payload = b"prepared bytes for the library handoff"
    sha = hashlib.sha256(payload).hexdigest()
    derived = folder / f"{sha}.mp4"
    derived.write_bytes(payload)
    return {
        "schema": SCHEMA,
        "original": {
            "path": str(clip.resolve()), "sha256": _sha(clip), "size_bytes": clip.stat().st_size,
            "width": 640, "height": 360, "frame_rate": "30/1",
        },
        "derived": {
            "path": str(derived), "sha256": sha, "size_bytes": len(payload), "frames": 41,
            "width": 640, "height": 360, "frame_rate": "30/1",
        },
        "settings": {"start_frame": 0, "end_frame": None, "fps_conversion": "none"},
        "contract": {
            "workflow_id": WAN_ANIMATE2_DRIVE_ID, "workflow_version": WAN_ANIMATE2_RUNTIME_VERSION,
            "output_frames": 41, "output_fps": 24,
            "runtime_revision": "6b747c0428c343e1417219641db93a4fb7cb69ae", "consumption_rule": "rule",
        },
        "plan": {"source_indices": list(range(41)), "window_frames": 100},
        "processing": {"tool": "ffmpeg", "lossless": True},
    }  # fmt: skip


# --- controller seam ------------------------------------------------------------------------------


@pytest.fixture
def isolated_user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    monkeypatch.delenv("STABLENEW_MOTION_LIBRARY_DIR", raising=False)
    return tmp_path


def test_an_unconfigured_library_is_explained_not_created(isolated_user_dir) -> None:
    controller, _ = _stack(isolated_user_dir)
    snapshot = controller.motion_library_snapshot()
    assert snapshot.configured is False and snapshot.assets == () and snapshot.suggested_root
    assert not (isolated_user_dir / "appdata").exists()
    with pytest.raises(Exception, match="No Motion Library folder"):
        controller.import_motion_video(isolated_user_dir / "x.mp4")


@needs_ffmpeg
def test_the_controller_imports_inspects_and_hands_off_a_real_clip(isolated_user_dir) -> None:
    tmp = isolated_user_dir
    controller, service = _stack(tmp)
    controller.configure_motion_library(tmp / "my library")
    clip = make_clip(tmp / "src", "walk.mp4", frames=24, rate=24)

    outcome = controller.import_motion_video(clip, annotations={"tags": "walk"})

    assert outcome.status == OUTCOME_IMPORTED
    snapshot = controller.motion_library_snapshot()
    assert snapshot.configured and len(snapshot.assets) == 1
    [asset] = snapshot.assets
    assert (
        snapshot.thumbnails[asset.asset_id]
        and snapshot.checks[asset.asset_id].state == "unverified"
    )
    inspection = controller.inspect_motion_asset(asset.asset_id)
    assert len(inspection.frames) == 3 and inspection.facts is not None
    plan = controller.plan_motion_library_handoff(
        asset.asset_id, WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION
    )
    assert plan.ok and plan.form_fields[FIELD_DRIVING_VIDEO] == str(clip.resolve())
    assert not controller.plan_motion_library_handoff(asset.asset_id, TI2V_ID).ok
    assert service.calls == []  # import, inspect and planning never reach JobService
    # A fresh controller (a restart) finds the same stable asset.
    again, _ = _stack(tmp)
    assert [a.asset_id for a in again.motion_library_snapshot().assets] == [asset.asset_id]


def test_the_controller_adds_a_completed_history_job_by_id(isolated_user_dir) -> None:
    tmp = isolated_user_dir
    repository, job_id, _ = _completed_job(tmp)
    clip = _clip_for(tmp)
    finish(repository, job_id, JobStatus.COMPLETED, result=video_result(clip))
    app, controller, service = make_app(tmp, repository=repository)
    controller.configure_motion_library(tmp / "lib")

    # Placeholder bytes cannot be probed, so script the inspection the way a real probe would answer.
    from src.controller import video_motion_library_controller as module

    original = module.import_history_video
    module.import_history_video = lambda *a, **k: original(*a, **{**k, "inspect": FakeInspector()})
    try:
        outcome = controller.add_job_to_motion_library(job_id, motion_label="turn")
        missing = controller.add_job_to_motion_library("no-such-job")
    finally:
        module.import_history_video = original

    assert outcome.status == OUTCOME_IMPORTED and missing.status == OUTCOME_FAILED
    assert service.calls == []  # adding a clip to the library queued nothing
    assert controller.motion_library().require(outcome.asset_id).origin.job_id == job_id


_IMPORT_PROBE = """
import socket, subprocess, sys, threading

class NoProcess(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        raise AssertionError("process started at import")

def no_connection(*args, **kwargs):
    raise AssertionError("network use at import")

subprocess.Popen = NoProcess
socket.socket.connect = no_connection
import src.video.motion_library.importer
import src.video.motion_library.handoff
import src.video.motion_library.relink
import src.video.motion_library.snapshot
import src.controller.video_motion_library_controller
assert threading.active_count() == 1, threading.enumerate()
assert "src.controller.job_service" not in sys.modules
"""


def test_importing_the_library_modules_starts_no_process_thread_or_connection() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE], cwd=root, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
