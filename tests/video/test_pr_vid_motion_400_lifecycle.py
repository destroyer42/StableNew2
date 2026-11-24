"""PR-VID-MOTION-400: the asset lifecycle around a harvest (manifest compatibility, lineage, search, handoff).

Placeholder clips with a scripted inspector for pure catalog rules; one tiny real FFmpeg clip where a harvested
derivative must really exist.  Nothing here starts a runtime, queues a real job or touches the network.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.video_workflow_controller import VideoWorkflowController
from src.queue.job_model import JobStatus
from src.video.motion_library.handoff import plan_driving_handoff
from src.video.motion_library.harvest import (
    HarvestRequest,
    describe_harvest,
    harvest_motion,
)
from src.video.motion_library.harvest_lineage import (
    lineage_from_asset,
    lineage_from_history,
    path_only,
)
from src.video.motion_library.importer import import_video
from src.video.motion_library.models import (
    CADENCE_NATIVE,
    LINEAGE_NONE,
    LINEAGE_PATH_ONLY,
    LINEAGE_RECORDED,
    LINEAGE_VERIFIED,
    AssetFormatError,
    HarvestRecord,
    MotionAsset,
)
from src.video.motion_library.search import SearchQuery, search_assets
from src.video.motion_library.store import MotionLibraryStore
from src.video.video_workflow_njr_builder import MOTION_LIBRARY_ASSET_FIELD
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from tests.helpers.make_video_313 import TI2V_ID
from tests.helpers.motion_library_353 import (
    FakeInspector,
    make_clip,
    needs_ffmpeg,
    new_store,
    write_clip,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(**changes: Any) -> HarvestRecord:
    base: dict[str, Any] = {
        "original_sha256": "a" * 64,
        "start_frame": 4,
        "end_frame": 28,
        "cadence": CADENCE_NATIVE,
        "original_path": "C:/videos/original.mp4",
        "original_name": "original.mp4",
        "original_frame_rate": "24/1",
        "original_frame_count": 48,
        "derivative_frames": 24,
        "derivative_frame_rate": "24/1",
    }
    base.update(changes)
    return HarvestRecord(**base)


def _service_stack(tmp_path: Path):
    class _Jobs:
        def __init__(self) -> None:
            self.calls: list[list[Any]] = []

        def submit_njrs(self, njrs, policy):
            self.calls.append(list(njrs))
            return [str(n.job_id) for n in njrs]

    jobs = _Jobs()
    app = SimpleNamespace(job_service=jobs, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app), jobs


# ------------------------------------------------------------------------------ manifest compatibility


def test_a_manifest_written_before_harvesting_loads_unchanged_and_keeps_unknown_fields(
    tmp_path: Path,
) -> None:
    store = new_store(tmp_path)
    clip = write_clip(tmp_path / "walk.mp4")
    asset_id = import_video(store, clip, inspect=FakeInspector()).asset_id
    manifest = store.manifest_path
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    record = payload["assets"][0]
    for key in ("harvest", "motion_label", "motion_achieved", "known_defects", "reuse_conditions"):
        record.pop(key, None)  # exactly what a pre-harvest writer produced
    record["written_by_a_newer_build"] = {"keep": "me"}
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    reopened = MotionLibraryStore(store.root)
    asset = reopened.require(asset_id)
    assert asset.harvest is None and not asset.is_harvested
    assert asset.effective_motion_label == "" and asset.effective_motion_achieved is None
    reopened.annotate(asset_id, {"motion_label": "walks left", "motion_achieved": True})
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["version"] == 1 and saved["schema"] == payload["schema"]
    assert saved["assets"][0]["written_by_a_newer_build"] == {"keep": "me"}
    assert saved["assets"][0]["motion_label"] == "walks left"
    assert saved["assets"][0]["motion_achieved"] is True


def test_a_harvest_record_round_trips_and_ignores_values_it_cannot_trust() -> None:
    record = _record(warnings=("one",), lineage_state=LINEAGE_VERIFIED, lineage_job_id="job-1")
    again = HarvestRecord.from_dict(record.to_dict())
    assert again == record
    with pytest.raises(AssetFormatError):  # no original identity: not a harvest
        HarvestRecord.from_dict({"start_frame": 3})
    with pytest.raises(AssetFormatError):
        HarvestRecord.from_dict("not a mapping")
    broken = record.to_dict()
    broken["end_frame"] = broken["start_frame"]  # an empty window is not a clip
    with pytest.raises(AssetFormatError):
        HarvestRecord.from_dict(broken)


def test_an_unreadable_harvest_record_is_reported_and_kept_verbatim(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    clip = write_clip(tmp_path / "walk.mp4")
    asset_id = import_video(store, clip, inspect=FakeInspector()).asset_id
    payload = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    payload["assets"][0]["harvest"] = {"schema": "stablenew.motion-harvest.v99", "junk": True}
    store.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    reopened = MotionLibraryStore(store.root)

    assert reopened.get(asset_id) is None  # not guessed at, not usable as a catalog entry ...
    assert any(
        "could not be read" in issue for issue in reopened.report.issues
    )  # ... but said aloud
    kept = _asset(reopened, tmp_path, "another")  # the library keeps working
    saved = json.loads(reopened.manifest_path.read_text(encoding="utf-8"))
    assert payload["assets"][0] in saved["unparsed"]  # ... and the record is written back unchanged
    assert reopened.get(kept) is not None


def test_opinions_stay_separate_and_are_never_transfer_evidence() -> None:
    clip = MotionAsset.from_dict(
        {
            "asset_id": "mlib_" + "1" * 32,
            "display_name": "wave",
            "sha256": "c" * 64,
            "locator": {"mode": "linked", "path": "x.mp4"},
            "visual_quality": "excellent",
            "motion_achieved": False,
            "good_for_motion": True,
        }
    )
    assert clip is not None
    assert (clip.visual_quality, clip.effective_motion_achieved, clip.good_for_motion) == (
        "excellent",
        False,
        True,
    )


# ------------------------------------------------------------------------------ search


def _asset(store: MotionLibraryStore, tmp_path: Path, name: str, **notes: Any) -> str:
    clip = write_clip(tmp_path / f"{name}.mp4", name.encode())
    return import_video(
        store, clip, annotations={"display_name": name, **notes}, inspect=FakeInspector()
    ).asset_id


def test_new_filters_select_on_recorded_facts_and_opinions(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    plain = _asset(store, tmp_path, "plain")
    kept = _asset(
        store,
        tmp_path,
        "kept",
        motion_achieved=True,
        visual_quality="good",
        start_pose="arms down",
        end_pose="arms up",
        known_defects="hand blur",
        motion_label="wave hello",
    )
    harvested = _asset(store, tmp_path, "cut")
    store.attach_harvest(harvested, _record())
    assets = store.assets()

    def ids(**kw: Any) -> set[str]:
        return {a.asset_id for a in search_assets(assets, SearchQuery(**kw))}

    assert ids(harvested_only=True) == {harvested}
    assert ids(harvested_only=True, cadence="native") == {harvested}
    assert ids(cadence="normalized_24") == set()  # only harvested clips have a cadence
    assert ids(motion_achieved_only=True) == {kept}
    assert ids(visual_quality="good") == {kept}
    assert ids(start_pose="ARMS DOWN") == {kept}
    assert ids(end_pose="up") == {kept}
    assert ids(text="blur") == {kept}  # known defects are searchable
    assert ids(text="wave hello") == {kept}
    assert ids(text="original.mp4") == {harvested}  # so is the harvested clip's original name
    assert ids() == {plain, kept, harvested}


# ------------------------------------------------------------------------------ store


def test_attach_harvest_keeps_the_first_cut_and_find_harvest_matches_only_the_same_cut(
    tmp_path: Path,
) -> None:
    store = new_store(tmp_path)
    asset_id = _asset(store, tmp_path, "cut")
    first = _record()
    store.attach_harvest(asset_id, first)
    store.attach_harvest(
        asset_id, _record(start_frame=10, end_frame=20)
    )  # a duplicate of the bytes

    assert store.require(asset_id).harvest == first
    assert store.find_harvest(first).asset_id == asset_id
    assert store.find_harvest(_record(end_frame=29)) is None
    assert store.find_harvest(_record(cadence="normalized_24")) is None
    assert [a.asset_id for a in store.harvests_of("a" * 64)] == [asset_id]


# ------------------------------------------------------------------------------ lineage


def _history_entry(
    tmp_path: Path, video: Path, *, status: JobStatus = JobStatus.COMPLETED, **bundle: Any
):
    payload = {"primary_path": str(video), **bundle}
    return SimpleNamespace(
        job_id="job-7", status=status, result={"video_bundle": payload}, snapshot={}
    )


def test_job_identity_is_verified_only_by_history_plus_the_file_hash(tmp_path: Path) -> None:
    video = write_clip(tmp_path / "out" / "gen.mp4", b"generated")
    digest = _sha(video)

    verified = lineage_from_history(
        _history_entry(tmp_path, video, sha256=digest), str(video), digest, job_id="job-7"
    )
    assert (verified.state, verified.job_id) == (LINEAGE_VERIFIED, "job-7")

    recorded = lineage_from_history(
        _history_entry(tmp_path, video), str(video), digest, job_id="job-7"
    )
    assert recorded.state == LINEAGE_RECORDED  # named, but the bytes were not hashed by History

    mismatched = lineage_from_history(
        _history_entry(tmp_path, video, sha256="0" * 64), str(video), digest, job_id="job-7"
    )
    assert mismatched.state == LINEAGE_PATH_ONLY and not mismatched.job_id

    other = write_clip(tmp_path / "out" / "other.mp4", b"another file")
    different_file = lineage_from_history(
        _history_entry(tmp_path, video, sha256=digest), str(other), _sha(other), job_id="job-7"
    )
    assert different_file.state == LINEAGE_PATH_ONLY and not different_file.job_id

    failed = lineage_from_history(
        _history_entry(tmp_path, video, status=JobStatus.FAILED, sha256=digest),
        str(video),
        digest,
        job_id="job-7",
    )
    assert failed.state == LINEAGE_PATH_ONLY
    assert lineage_from_history(None, str(video), digest, job_id="job-7").state == LINEAGE_PATH_ONLY
    assert path_only(str(video)).state == LINEAGE_PATH_ONLY


def test_a_file_name_or_folder_never_establishes_a_job(tmp_path: Path) -> None:
    video = write_clip(tmp_path / "job-7" / "job-7_final.mp4", b"looks generated")
    assert lineage_from_history(None, str(video), _sha(video)).state == LINEAGE_PATH_ONLY


def test_a_library_asset_passes_its_own_lineage_on_without_strengthening_it(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    asset_id = _asset(store, tmp_path, "cut")
    plain = store.require(asset_id)
    assert lineage_from_asset(plain).state == LINEAGE_NONE

    store.attach_harvest(asset_id, _record(lineage_state=LINEAGE_RECORDED, lineage_job_id="job-9"))
    inherited = lineage_from_asset(store.require(asset_id))
    assert (inherited.state, inherited.job_id) == (LINEAGE_RECORDED, "job-9")


def test_describe_harvest_states_what_is_known_without_claiming_more() -> None:
    lines = " ".join(describe_harvest(_record(), original_present=False))
    assert "frames 4-27" in lines
    assert "NOT found" in lines and "unaffected" in lines
    assert "recorded path" in " ".join(describe_harvest(_record(), original_present=True))
    assert describe_harvest(_record(), original_present=None)  # the pane may not know yet


# ------------------------------------------------------------------------------ driving handoff


def _meta(controller: VideoWorkflowController, workflow_id: str) -> dict[str, Any]:
    return next(s for s in controller.list_workflow_specs() if s["workflow_id"] == workflow_id)


@needs_ffmpeg
def test_a_harvested_asset_uses_the_existing_driving_handoff_and_records_its_cut(
    tmp_path: Path,
) -> None:
    controller, jobs = _service_stack(tmp_path)
    store = new_store(tmp_path)
    original = make_clip(tmp_path, "original.mp4", frames=48)
    outcome = harvest_motion(
        store, HarvestRequest(source_path=str(original), start=6, end=30, name="wave")
    )
    assert outcome.ok, outcome.message
    asset = store.require(outcome.asset_id)
    derivative = store.asset_path(asset)

    plan = plan_driving_handoff(store, asset.asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))

    assert plan.ok, plan.refusal
    assert list(plan.form_fields) == ["pose_video_path"]  # only the driving-video field is filled
    assert plan.form_fields["pose_video_path"] == str(derivative.resolve())
    assert plan.binding["asset_id"] == asset.asset_id and plan.binding["sha256"] == _sha(derivative)
    derived = plan.binding["derived_from"]
    assert derived == {
        "original_sha256": _sha(original),
        "start_frame": 6,
        "end_frame": 30,
        "cadence": CADENCE_NATIVE,
    }
    assert jobs.calls == []  # planning queued nothing


@needs_ffmpeg
def test_submission_freezes_the_harvested_identity_and_fails_closed_when_it_is_swapped(
    tmp_path: Path,
) -> None:
    from PIL import Image

    controller, jobs = _service_stack(tmp_path)
    store = new_store(tmp_path)
    original = make_clip(tmp_path, "original.mp4", frames=48)
    outcome = harvest_motion(
        store, HarvestRequest(source_path=str(original), start=0, end=24, name="wave")
    )
    asset = store.require(outcome.asset_id)
    derivative = store.asset_path(asset)
    plan = plan_driving_handoff(store, asset.asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))
    portrait = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(portrait)
    form = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_RUNTIME_VERSION,
        "prompt": "A person in a studio",
        "negative_prompt": "",
        "pose_video_path": str(derivative),
        "experimental_opt_in": True,
        "seed": "424242",
        "frame_count": "41",
        "operator_controls": {"pose_prompt": "waves", "pose_strength": "1"},
        MOTION_LIBRARY_ASSET_FIELD: plan.binding,
    }

    controller.submit_video_workflow_job(source_image_path=portrait, form_data=dict(form))

    [njr] = jobs.calls[-1]
    frozen = njr.extra_metadata["video_workflow"]["motion_library_asset"]
    assert frozen["asset_id"] == asset.asset_id and frozen["sha256"] == _sha(derivative)
    assert frozen["derived_from"]["start_frame"] == 0 and frozen["derived_from"]["end_frame"] == 24
    assert "original_path" not in json.dumps(frozen)  # provenance only; no path leaks into the job
    assert len(jobs.calls) == 1

    derivative.write_bytes(derivative.read_bytes() + b"swapped")
    with pytest.raises(ValueError, match="no longer matches the Motion Library clip"):
        controller.submit_video_workflow_job(source_image_path=portrait, form_data=dict(form))
    assert len(jobs.calls) == 1  # the swapped file never reached the queue


def test_a_workflow_that_takes_no_driving_video_refuses_a_harvested_asset_too(
    tmp_path: Path,
) -> None:
    controller, _ = _service_stack(tmp_path)
    store = new_store(tmp_path)
    asset_id = _asset(store, tmp_path, "cut")
    store.attach_harvest(asset_id, _record())

    plan = plan_driving_handoff(store, asset_id, _meta(controller, TI2V_ID))

    assert not plan.ok and plan.form_fields == {} and plan.binding == {}


def test_a_missing_original_never_blocks_a_verified_derivative(tmp_path: Path) -> None:
    controller, _ = _service_stack(tmp_path)
    store = new_store(tmp_path)
    clip = write_clip(tmp_path / "cut.mp4", b"derivative bytes")
    asset_id = import_video(
        store,
        clip,
        annotations={"display_name": "cut"},
        inspect=FakeInspector(),
        harvest=_record(original_path=str(tmp_path / "gone.mp4")),
    ).asset_id

    plan = plan_driving_handoff(store, asset_id, _meta(controller, WAN_ANIMATE2_DRIVE_ID))

    assert plan.ok, plan.refusal
    assert plan.binding["derived_from"]["original_sha256"] == "a" * 64


# ------------------------------------------------------------------------------ controller seam


@pytest.fixture
def isolated_user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    monkeypatch.delenv("STABLENEW_MOTION_LIBRARY_DIR", raising=False)
    return tmp_path


def _completed_history_job(tmp: Path, clip: Path, *, record_sha: bool):
    from tests.helpers.make_video_313 import make_app, make_image
    from tests.helpers.video_review_211 import finish, new_repository, persist, video_result

    app, controller, service = make_app(tmp)
    controller.submit_video_workflow_job(
        source_image_path=make_image(tmp / "start.png"),
        form_data={
            "workflow_id": TI2V_ID,
            "workflow_version": "1.2.0",
            "prompt": "a person waves",
            "seed": "5",
        },
    )
    repository = new_repository(tmp, "history.sqlite3")
    [job_id] = persist(repository, [service.submitted[-1]])
    result = video_result(clip)
    if record_sha:
        result["video_bundle"]["sha256"] = _sha(clip)
    finish(repository, job_id, JobStatus.COMPLETED, result=result)
    app, controller, service = make_app(tmp, repository=repository)
    return controller, service, job_id


@needs_ffmpeg
@pytest.mark.parametrize(
    ("record_sha", "state"), [(True, LINEAGE_VERIFIED), (False, LINEAGE_RECORDED)]
)
def test_the_controller_harvests_a_history_video_keeps_its_lineage_and_queues_nothing(
    isolated_user_dir: Path, record_sha: bool, state: str
) -> None:
    from src.video.motion_library.harvest_service import HarvestSourceRef

    tmp = isolated_user_dir
    clip = make_clip(tmp / "output", "generated.mp4", frames=48)
    original_bytes = clip.read_bytes()
    controller, service, job_id = _completed_history_job(tmp, clip, record_sha=record_sha)
    controller.configure_motion_library(tmp / "library")
    assert controller.motion_library_ready()
    submitted = len(service.submitted)

    info = controller.open_harvest_source(HarvestSourceRef(path=str(clip), job_id=job_id))
    assert info.ok and (info.lineage.state, info.lineage.job_id) == (state, job_id)
    outcome = controller.harvest_motion_window(
        HarvestRequest(
            source_path=info.path,
            start=8,
            end=32,
            name="wave",
            annotations={"motion_label": "waves"},
            lineage=info.lineage,
        )
    )

    assert outcome.ok, outcome.message
    asset = controller.motion_library().require(outcome.asset_id)
    assert asset.harvest is not None
    assert (asset.harvest.lineage_state, asset.harvest.lineage_job_id) == (state, job_id)
    assert asset.motion_label == "waves" and asset.frame_count == 24
    assert clip.read_bytes() == original_bytes  # the generated original is untouched
    assert len(service.submitted) == submitted and service.calls == []  # no job was built or queued


def test_without_a_library_a_video_can_still_be_opened_but_not_harvested(
    isolated_user_dir: Path,
) -> None:
    from src.video.motion_library.harvest import STATUS_REFUSED
    from src.video.motion_library.harvest_service import HarvestSourceRef
    from tests.helpers.make_video_313 import make_app

    _, controller, service = make_app(isolated_user_dir)
    clip = write_clip(isolated_user_dir / "x.mp4", b"not decodable")

    assert not controller.motion_library_ready()
    info = controller.open_harvest_source(HarvestSourceRef(path=str(clip)))
    assert not info.ok and info.error  # unreadable bytes are explained, not raised
    refused = controller.harvest_motion_window(HarvestRequest(source_path=str(clip), name="x"))
    assert refused.status == STATUS_REFUSED and "No Motion Library folder" in refused.message
    assert service.calls == []


_IMPORT_PROBE = """
import socket, subprocess, sys, threading

class NoProcess(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        raise AssertionError("process started at import")

def no_connection(*args, **kwargs):
    raise AssertionError("network use at import")

subprocess.Popen = NoProcess
socket.socket.connect = no_connection
import src.video.motion_library.harvest
import src.video.motion_library.harvest_lineage
import src.video.motion_library.harvest_service
import src.video.motion_library.harvest_window
import src.video.motion_library.harvest_workflow_preview
import src.gui.view_contracts.motion_harvest_contract
assert threading.active_count() == 1, threading.enumerate()
assert "src.controller.job_service" not in sys.modules
assert "tkinter" not in sys.modules, "the harvest session must stay toolkit-neutral"
"""


def test_importing_the_harvest_modules_starts_no_process_thread_connection_or_toolkit() -> None:
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(root)},
    )
    assert result.returncode == 0, result.stderr
