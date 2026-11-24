"""PR-VID-STORY-IMPORT: an MP4 the operator picked becomes a Storyboard root.

Known StableNew clips keep their job-based root; any other MP4 is probed, checked against the approved workflow, decoded
once and published through the same staging as every root. The probe and the decoder are injected fakes writing small real
PNGs, the registry and NJR builder are the real ones, and the job service is a recording fake: nothing starts FFmpeg,
Comfy, a GPU or a network, and no test submits a generation job except the admission checks that do so through the fake.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.runtime_state import CancellationError, CancelToken
from src.controller.storyboard_submission_service import (
    ContinueRequest,
    ContinueRow,
    StoryboardSubmissionService,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import JobStatus
from src.video.driving_video_inspection import (
    STATUS_FAILED,
    STATUS_OK,
    DrivingVideoFacts,
    DrivingVideoInspection,
    InspectionIssue,
)
from src.video.sequence_frames import SequenceFrameError
from src.video.sequence_ledger import sha256_of
from src.video.sequence_plan import ROOT_PARENT, SequencePlan
from src.video.storyboard_cut import BASIS_DECODED, read_cut_manifest
from src.video.storyboard_cuts import root_cut
from src.video.storyboard_import import (
    FRAMES_FOLDER,
    IMPORT_RECORD_NAME,
    AmbiguousKnownClip,
    ClipFacts,
    ClipImporter,
    ClipImportError,
    ConversionNotAccepted,
    KnownClipRefused,
    assess_clip,
    default_clip_folder,
    inspect_clip,
    read_import_record,
    resolve_known_clip,
    source_text,
    suggest_title,
)
from src.video.storyboard_tree import StoryboardTree, StoryboardTreeError, TreeRoot
from src.video.storyboard_tree_store import StoryboardTreeStore
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION
from tests.helpers.storyboard_380 import (
    A14B_SIZE,
    REG,
    TI2V_ID,
    FakeDecoder,
    FakeRepository,
    builder,
    frames_out_job,
)

SID = "i" * 32
A14B = {"workflow_id": WAN_A14B_ID, "workflow_version": WAN_A14B_VERSION, "frame_count": 17}


# --------------------------------------------------------------------------------------------- fakes


def probe(
    *,
    size: tuple[int, int] = A14B_SIZE,
    fps: float | None = 16.0,
    rational: str = "16/1",
    frames: int | None = 17,
    variable: bool = False,
    sar: str = "1:1",
    basis: str = "reported",
) -> DrivingVideoFacts:
    return DrivingVideoFacts(
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        codec_name="h264",
        pixel_format="yuv420p",
        coded_width=size[0],
        coded_height=size[1],
        rotation_quadrants=0,
        display_width=size[0],
        display_height=size[1],
        sample_aspect_ratio=sar,
        reported_fps=fps,
        fps_basis="average",
        fps_is_variable_suspected=variable,
        reported_frame_count=frames if basis == "reported" else None,
        estimated_frame_count=frames if basis == "estimated" else None,
        frame_count_basis=basis,
        duration_seconds=None if fps is None or frames is None else frames / fps,
        duration_basis="stream",
        fps_rational=rational,
    )


class FakeInspector:
    """The existing probe's answer for any file, without running FFprobe."""

    def __init__(self, facts: DrivingVideoFacts | None = None, *, fail: str = "") -> None:
        self.facts = facts or probe()
        self.fail = fail
        self.calls: list[Path] = []

    def __call__(self, path: Path, **_kw: Any) -> DrivingVideoInspection:
        self.calls.append(Path(path))
        if self.fail:
            return DrivingVideoInspection(
                str(path),
                STATUS_FAILED,
                issues=(InspectionIssue("probe_failed", self.fail),),
            )
        return DrivingVideoInspection(str(path), STATUS_OK, facts=self.facts)


def mp4(
    folder: Path, name: str = "clip.mp4", payload: bytes = b"\x00\x00\x00\x18ftypmp42 body"
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(payload)
    return path


class Repo(FakeRepository):
    """``FakeRepository`` plus the newest-first listing the known-clip search reads."""

    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [SimpleNamespace(job_id=job_id) for job_id in reversed(list(self.jobs))][:limit]


def importer(
    tmp_path: Path,
    *,
    repository: Any = None,
    decoder: Any = None,
    inspector: Any = None,
) -> ClipImporter:
    repo = repository if repository is not None else Repo()
    return ClipImporter(
        repository=lambda: repo,
        registry=REG,
        output_root=lambda: str(tmp_path / "out"),
        decode_clip=decoder or FakeDecoder(count=17, size=A14B_SIZE),
        inspector=inspector or FakeInspector(),
    )


def prepare(tmp_path: Path, clip: Path, **kw: Any):
    choices = {
        k: kw.pop(k) for k in ("expected_sha256", "accept_conversion", "import_as_media") if k in kw
    }
    settings = kw.pop("settings", A14B)
    return importer(tmp_path, **kw).prepare(clip, settings, SID, **choices)


def root_folder(tmp_path: Path) -> Path:
    return tmp_path / "out" / "storyboards" / SID / "root"


def nothing_published(tmp_path: Path) -> bool:
    base = tmp_path / "out" / "storyboards"
    return not base.exists() or not any(base.rglob("*"))


# --------------------------------------------------------------------------------------------- browsing and inspection


def test_the_browser_opens_in_movie_clips_and_falls_back_gracefully(tmp_path):
    out = tmp_path / "output"
    assert default_clip_folder(out) == str(Path.home().resolve())  # nothing exists yet
    out.mkdir()
    assert default_clip_folder(out) == str(out.resolve())  # no movie_clips folder: the output root
    (out / "movie_clips").mkdir()
    assert default_clip_folder(out) == str((out / "movie_clips").resolve())
    assert default_clip_folder(None) == str(Path.home().resolve())


def test_title_is_suggested_from_the_file_name():
    assert suggest_title(r"C:\clips\diner_arrest-scene.v2.MP4") == "diner arrest scene v2"
    assert suggest_title("/x/___.mp4") == "Imported clip"


def test_inspection_reports_identity_and_media_facts_without_touching_the_file(tmp_path):
    clip = mp4(tmp_path / "somewhere" / "else", "Mine.MP4")
    before = (sha256_of(clip), clip.stat().st_mtime_ns)
    facts = inspect_clip(clip, inspector=FakeInspector(probe(frames=33)))
    assert (facts.filename, facts.width, facts.height, facts.fps, facts.frame_count) == (
        "Mine.MP4",
        832,
        480,
        16.0,
        33,
    )
    assert facts.sha256 == before[0] and Path(facts.path) == clip.resolve()
    assert (sha256_of(clip), clip.stat().st_mtime_ns) == before
    assert any("832×480" in line and "16 fps" in line for line in facts.lines())


@pytest.mark.parametrize(
    ("name", "payload", "message"),
    [
        ("clip.mov", b"x", "not an MP4"),
        ("missing.mp4", None, "does not exist"),
        ("e.mp4", b"", "empty"),
    ],
)
def test_inspection_refuses_unusable_files_with_a_reason(tmp_path, name, payload, message):
    path = tmp_path / name
    if payload is not None:
        path.write_bytes(payload)
    with pytest.raises(ClipImportError, match=message):
        inspect_clip(path, inspector=FakeInspector())


def test_a_corrupt_file_is_refused_with_the_probes_reason(tmp_path):
    clip = mp4(tmp_path)
    with pytest.raises(ClipImportError, match="cannot be inspected: FFprobe could not read"):
        inspect_clip(clip, inspector=FakeInspector(fail="FFprobe could not read this file"))


# --------------------------------------------------------------------------------------------- compatibility


def assess(facts_kwargs: dict[str, Any], settings: dict[str, Any] | None = None):
    given = probe(**facts_kwargs)
    clip_facts = ClipFacts(
        path="x.mp4",
        filename="x.mp4",
        size_bytes=1,
        sha256="a" * 64,
        width=given.display_width,
        height=given.display_height,
        fps=given.reported_fps,
        fps_rational=given.fps_rational,
        fps_variable=given.fps_is_variable_suspected,
        duration_seconds=given.duration_seconds,
        frame_count=given.frame_count,
        frame_count_basis=given.frame_count_basis,
        codec="h264",
        square_pixels=given.sample_aspect_ratio in ("", "1:1"),
    )
    return assess_clip(clip_facts, A14B if settings is None else settings, REG)


def test_a_clip_at_the_workflows_size_and_rate_needs_no_conversion():
    result = assess({})
    assert result.compatible and not result.needs_conversion
    assert result.target_size == A14B_SIZE and result.fps == 16
    assert "no conversion is needed" in result.lines()[0]


def test_a_larger_clip_proposes_a_cover_resize_and_says_what_is_lost():
    result = assess({"size": (1920, 1080)})
    assert result.compatible and result.needs_conversion
    text = " ".join(result.lines())
    assert "1920×1080 → 832×480" in text and "never stretched" in text and "cropped away" in text


def test_a_portrait_clip_targets_the_portrait_size():
    result = assess({"size": (1080, 1920)})
    assert result.target_size == (480, 832)


def test_a_multiple_of_the_rate_keeps_every_nth_frame_and_drops_nothing_else():
    result = assess({"fps": 32.0, "rational": "32/1", "frames": 33})
    assert result.conversion is not None and result.conversion.keep_every == 2
    assert result.kept_frames == 17 and not result.conversion.retimed
    assert "never blended or invented" in " ".join(result.lines())


def test_a_rate_within_two_tenths_of_a_percent_is_relabelled_only_with_consent():
    result = assess({"fps": 15.984, "rational": "16000/1001"})
    assert result.compatible and result.conversion is not None and result.conversion.retimed
    assert "Timing" in " ".join(result.lines())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"fps": 30.0, "rational": "30/1"}, "invented or repeated frames"),
        ({"fps": None, "rational": ""}, "does not report a frame rate"),
        ({"variable": True}, "frame rate varies"),
        ({"sar": "4:3"}, "pixels are not square"),
        ({"frames": 401}, "at most 400"),
        ({"frames": 1}, "fewer than two"),
    ],
)
def test_unusable_media_is_blocked_with_an_actionable_reason(kwargs, message):
    result = assess(kwargs)
    assert not result.compatible
    assert message in " ".join(result.blockers)


def test_workflow_governance_is_not_bypassed():
    missing = assess({}, {})
    assert not missing.compatible and "needs a workflow" in missing.blockers[0]
    unknown = assess({}, {"workflow_id": "no_such_workflow"})
    assert not unknown.compatible
    # a workflow that follows a driving video cannot be continued by a sequence at all
    driving = assess({}, {"workflow_id": "wan_animate2_drive_i2v_v1", "workflow_version": "1.0.0"})
    assert not driving.compatible


def test_the_approved_workflow_of_another_rate_is_reported_per_workflow():
    result = assess({"fps": 24.0, "rational": "24/1"}, {"workflow_id": TI2V_ID})
    assert (
        result.fps == 24 or not result.compatible
    )  # whichever the catalog marks, never silently converted
    assert result.fps != 16


# --------------------------------------------------------------------------------------------- external roots


def test_an_external_mp4_becomes_a_root_with_no_job_behind_it(tmp_path):
    clip = mp4(tmp_path / "elsewhere", "other_app.MP4")
    before = (sha256_of(clip), clip.stat().st_mtime_ns)
    prepared = prepare(tmp_path, clip)
    folder = root_folder(tmp_path)
    cut = read_cut_manifest(prepared.manifest.path, expected_sha256=prepared.manifest.sha256)
    assert prepared.kind == "clip" and prepared.job_id is None and cut.job_id is None
    assert len(cut.frames) == 17 and (cut.width, cut.height, cut.fps) == (832, 480, 16)
    assert [r.basis for r in cut.ranges] == [BASIS_DECODED] and cut.ranges[0].owner == ROOT_PARENT
    assert all(Path(f.path).is_file() and sha256_of(f.path) == f.sha256 for f in cut.frames)
    assert {Path(f.path).parent for f in cut.frames} == {folder / FRAMES_FOLDER}
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [FRAMES_FOLDER, "root_cut.json", IMPORT_RECORD_NAME]
    )
    assert (sha256_of(clip), clip.stat().st_mtime_ns) == before  # AC-09: only read
    assert dict(prepared.settings)["workflow_id"] == WAN_A14B_ID
    assert prepared.external is not None and prepared.external["origin"] == "external"
    assert prepared.external["source_sha256"] == before[0]
    assert Path(prepared.external["source_path"]) == clip.resolve()


def test_the_record_pins_the_source_the_probe_and_the_conversion(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    prepared = prepare(tmp_path, clip)
    root = TreeRoot.from_dict(
        {
            "kind": "clip",
            "job_id": "",
            "image_path": "",
            "image_sha256": "",
            "manifest_path": prepared.manifest.path,
            "manifest_sha256": prepared.manifest.sha256,
            "settings": dict(prepared.settings),
            "fps": prepared.fps,
            "width": prepared.width,
            "height": prepared.height,
            "smoothing_text": "",
            **prepared.external,
        }
    )
    record = read_import_record(root)
    assert record["source"]["sha256"] == sha256_of(clip) and record["source"]["width"] == 832
    assert record["decode"]["basis"] == "decoded" and record["decode"]["frames_kept"] == 17
    assert record["conversion"]["resize"] is None and record["conversion"]["keep_every"] == 1
    assert record["known_stablenew_job"] is None
    assert "no StableNew job" in source_text(root)
    Path(root.source_record_path).write_text("{}", encoding="utf-8")
    with pytest.raises(ClipImportError, match="changed since it was written"):
        read_import_record(root)


def test_the_root_cut_continues_from_any_frame_not_just_the_ends(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    prepared = prepare(tmp_path, clip)
    cut = read_cut_manifest(prepared.manifest.path, expected_sha256=prepared.manifest.sha256)
    for index in (0, 5, len(cut.frames) - 1):
        prefix = cut.prefix(index + 1)
        assert len(prefix.frames) == index + 1 and prefix.frames[-1] == cut.frames[index]


def test_a_conversion_must_be_accepted_before_anything_is_made(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    inspector = FakeInspector(probe(size=(1280, 720)))
    with pytest.raises(ConversionNotAccepted, match="1280×720 → 832×480"):
        prepare(tmp_path, clip, inspector=inspector, decoder=FakeDecoder(17, (1280, 720)))
    assert nothing_published(tmp_path)


def test_an_accepted_conversion_makes_workflow_sized_frames_and_records_it(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    prepared = prepare(
        tmp_path,
        clip,
        accept_conversion=True,
        inspector=FakeInspector(probe(size=(1280, 720))),
        decoder=FakeDecoder(17, (1280, 720)),
    )
    cut = read_cut_manifest(prepared.manifest.path, expected_sha256=prepared.manifest.sha256)
    assert (cut.width, cut.height) == (832, 480) == (prepared.width, prepared.height)
    record = json.loads((root_folder(tmp_path) / IMPORT_RECORD_NAME).read_text("utf-8"))
    assert record["conversion"]["resize"]["from"] == [1280, 720]
    assert record["conversion"]["resize"]["to"] == [832, 480]
    assert not (root_folder(tmp_path) / "decoded").exists()  # the unconverted frames are not kept


def test_a_higher_frame_rate_keeps_every_nth_decoded_frame(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    prepared = prepare(
        tmp_path,
        clip,
        accept_conversion=True,
        inspector=FakeInspector(probe(fps=32.0, rational="32/1", frames=33)),
        decoder=FakeDecoder(33, A14B_SIZE),
    )
    cut = read_cut_manifest(prepared.manifest.path, expected_sha256=prepared.manifest.sha256)
    assert len(cut.frames) == 17 and cut.fps == 16


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("decode", "cannot be decoded"),
        ("count", "gave 12 frames but the file reports 17"),
        ("size", "refused rather than distorted"),
    ],
)
def test_a_failed_preparation_leaves_nothing_behind(tmp_path, failure, message):
    clip = mp4(tmp_path / "elsewhere")

    class Broken(FakeDecoder):
        def __call__(self, clip_path, out_dir, cancel_token=None):
            if failure == "decode":
                raise SequenceFrameError("FFmpeg could not decode clip.mp4: moov atom not found")
            return super().__call__(clip_path, out_dir, cancel_token)

    decoder = Broken(
        count=12 if failure == "count" else 17, size=(64, 48) if failure == "size" else A14B_SIZE
    )
    with pytest.raises(ClipImportError, match=message):
        prepare(tmp_path, clip, decoder=decoder)
    assert nothing_published(tmp_path)
    assert clip.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")


def test_a_file_that_changes_while_it_is_imported_is_refused(tmp_path):
    clip = mp4(tmp_path / "elsewhere")

    class Rewriting(FakeDecoder):
        def __call__(self, clip_path, out_dir, cancel_token=None):
            frames = super().__call__(clip_path, out_dir, cancel_token)
            Path(clip_path).write_bytes(b"changed underneath the import")
            return frames

    with pytest.raises(ClipImportError, match="changed while it was being imported"):
        prepare(tmp_path, clip, decoder=Rewriting(17, A14B_SIZE))
    assert nothing_published(tmp_path)


def test_a_file_changed_since_it_was_inspected_is_refused_before_decoding(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    decoder = FakeDecoder(17, A14B_SIZE)
    reviewed = sha256_of(clip)
    clip.write_bytes(b"someone replaced it after the operator reviewed it")
    with pytest.raises(ClipImportError, match="changed since it was inspected"):
        prepare(tmp_path, clip, expected_sha256=reviewed, decoder=decoder)
    assert decoder.calls == 0 and nothing_published(tmp_path)


def test_a_cancelled_import_leaves_nothing_behind(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    token = CancelToken()

    class Cancelling(FakeDecoder):
        def __call__(self, clip_path, out_dir, cancel_token=None):
            frames = super().__call__(clip_path, out_dir, cancel_token)
            token.cancel()
            return frames

    with pytest.raises(CancellationError):
        importer(tmp_path, decoder=Cancelling(17, A14B_SIZE)).prepare(
            clip, A14B, SID, cancel_token=token
        )
    assert nothing_published(tmp_path)


def test_an_existing_root_is_never_replaced(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    prepare(tmp_path, clip)
    with pytest.raises(Exception, match="already has a root"):
        prepare(tmp_path, clip)


# --------------------------------------------------------------------------------------------- known StableNew clips


def known_clip(tmp_path: Path, count: int = 17):
    repo, job_id, frames = frames_out_job(tmp_path / "out", count=count)
    shared = Repo()
    shared.jobs.update(repo.jobs)
    shared.files.update(repo.files)
    return shared, job_id, frames, shared.files[job_id]["unsmoothed"]


def test_a_recognised_clip_keeps_its_job_provenance_and_native_frames(tmp_path):
    repo, job_id, frames, clip = known_clip(tmp_path)
    known = resolve_known_clip(clip, repository=repo)
    assert (known.status, known.job_id) == ("unique", job_id)
    decoder = FakeDecoder(17, A14B_SIZE)
    prepared = importer(tmp_path, repository=repo, decoder=decoder).prepare(clip, A14B, SID)
    cut = read_cut_manifest(prepared.manifest.path, expected_sha256=prepared.manifest.sha256)
    assert prepared.job_id == job_id and prepared.external is None
    assert [f.path for f in cut.frames] == [
        str(p) for p in frames
    ]  # native frames, referenced in place
    assert [r.basis for r in cut.ranges] == ["native"] and decoder.calls == 0
    assert dict(prepared.settings)["workflow_id"] == WAN_A14B_ID


def test_the_file_name_alone_never_establishes_lineage(tmp_path):
    repo, _job_id, _frames, clip = known_clip(tmp_path)
    twin = mp4(tmp_path / "copies", clip.name, clip.read_bytes())
    assert resolve_known_clip(twin, repository=repo).status == "none"
    prepared = importer(tmp_path, repository=repo).prepare(twin, A14B, SID)
    assert prepared.job_id is None and prepared.external is not None


def test_two_jobs_recording_one_file_are_ambiguous_and_never_guessed(tmp_path):
    repo, job_id, _frames, clip = known_clip(tmp_path)
    other = repo.jobs[job_id]
    repo.jobs["job-twin"] = type(other)(
        "job-twin", other.status, other.result, other._normalized_record
    )
    known = resolve_known_clip(clip, repository=repo)
    assert known.status == "ambiguous" and set(known.job_ids) == {job_id, "job-twin"}
    with pytest.raises(AmbiguousKnownClip, match="ambiguous"):
        importer(tmp_path, repository=repo).prepare(clip, A14B, SID)
    assert nothing_published(tmp_path)


def test_known_clip_without_its_frames_is_refused_and_media_import_is_a_separate_choice(tmp_path):
    repo, job_id, frames, clip = known_clip(tmp_path)
    frames[3].unlink()
    imp = importer(tmp_path, repository=repo)
    with pytest.raises(KnownClipRefused, match="encoded MP4 itself as media") as raised:
        imp.prepare(clip, A14B, SID)
    assert raised.value.job_id == job_id and "frame 4" in raised.value.reason
    assert nothing_published(tmp_path)  # the integrity refusal was not bypassed
    prepared = imp.prepare(clip, A14B, SID, import_as_media=True)
    assert prepared.job_id is None and prepared.external is not None
    record = json.loads((root_folder(tmp_path) / IMPORT_RECORD_NAME).read_text("utf-8"))
    assert (
        job_id in record["known_stablenew_job"]
        and "imported the encoded MP4 as media" in record["known_stablenew_job"]
    )


def test_only_completed_job_output_paths_count(tmp_path):
    repo, job_id, _frames, clip = known_clip(tmp_path)

    class OnlyQueued(Repo):
        def list_recent_jobs(self, **_kw: Any) -> list[Any]:
            return []

    empty = OnlyQueued()
    assert resolve_known_clip(clip, repository=empty).status == "none"
    assert resolve_known_clip(clip, repository=object()).status == "none"
    assert repo.jobs[job_id].status == JobStatus.COMPLETED


# --------------------------------------------------------------------------------------------- persistence compatibility


LEGACY_ROOT = {
    "kind": "clip",
    "job_id": "job-1",
    "image_path": "",
    "image_sha256": "",
    "manifest_path": "m.json",
    "manifest_sha256": "a" * 64,
    "settings": {"workflow_id": "w"},
    "fps": 16,
    "width": 8,
    "height": 8,
    "smoothing_text": "",
}


def test_a_root_written_before_this_change_reads_and_saves_identically():
    root = TreeRoot.from_dict(dict(LEGACY_ROOT))
    assert root.origin == "job" and root.source_path == ""
    assert root.to_dict() == LEGACY_ROOT  # not one new key in an existing file


def test_an_external_root_survives_saving_and_reopening(tmp_path):
    clip = mp4(tmp_path / "elsewhere")
    prepared = prepare(tmp_path, clip)
    store = StoryboardTreeStore(tmp_path / "trees")
    root = TreeRoot.from_dict(
        {
            **LEGACY_ROOT,
            "job_id": "",
            "manifest_path": prepared.manifest.path,
            "manifest_sha256": prepared.manifest.sha256,
            "settings": dict(prepared.settings),
            "fps": 16,
            "width": 832,
            "height": 480,
            **prepared.external,
        }
    )
    saved = store.save(StoryboardTree.new("Imported", root))
    reopened = store.load(saved.storyboard_id)
    assert reopened.root == root and reopened.root.origin == "external"
    assert reopened.root.source_sha256 == sha256_of(clip)  # AC-20: both identities survive
    assert reopened.root.manifest_sha256 == prepared.manifest.sha256
    assert len(root_cut(reopened.root).frames) == 17


@pytest.mark.parametrize(
    "change",
    [
        {"job_id": "job-9"},  # an external root never claims a job
        {"kind": "image"},
        {"source_path": ""},
        {"origin": "job"},
    ],
)
def test_a_malformed_external_root_is_refused(change):
    external = {
        **LEGACY_ROOT,
        "job_id": "",
        "origin": "external",
        "source_path": "c.mp4",
        "source_sha256": "b" * 64,
        "source_record_path": "r.json",
        "source_record_sha256": "c" * 64,
    }
    TreeRoot.from_dict(external)
    with pytest.raises(StoryboardTreeError):
        TreeRoot.from_dict({**external, **change})


def test_a_partial_set_of_source_fields_is_refused():
    with pytest.raises(StoryboardTreeError, match="needs all its source fields"):
        TreeRoot.from_dict({**LEGACY_ROOT, "origin": "external"})
    with pytest.raises(StoryboardTreeError, match="needs all its source fields"):
        TreeRoot.from_dict({**LEGACY_ROOT, "source_path": "c.mp4"})


# --------------------------------------------------------------------------------------------- submission service


class Queue:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.njrs: list[NormalizedJobRecord] = []

    def submit_njrs(self, njrs: list[NormalizedJobRecord], policy: Any) -> list[str]:
        self.calls.append(len(njrs))
        self.njrs.extend(njrs)
        return [str(n.job_id) for n in njrs]


def make_service(tmp_path: Path, **kw: Any) -> tuple[StoryboardSubmissionService, Queue]:
    queue = Queue()
    repo = kw.pop("repository", Repo())
    service = StoryboardSubmissionService(
        njr_builder=builder(tmp_path / "out"),
        workflow_registry=REG,
        job_service=lambda: queue,
        repository=lambda: repo,
        store=StoryboardTreeStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path / "out"),
        clip_importer=ClipImporter(
            repository=lambda: repo,
            registry=REG,
            output_root=lambda: str(tmp_path / "out"),
            decode_clip=kw.pop("decoder", FakeDecoder(17, A14B_SIZE)),
            inspector=kw.pop("inspector", FakeInspector()),
        ),
    )
    return service, queue


def request(
    tree: StoryboardTree, *, mode: str, index: int | None, rows: int = 2, seed: str = ""
) -> ContinueRequest:
    return ContinueRequest(
        storyboard_id=tree.storyboard_id,
        expected_revision=tree.revision,
        parent_id=ROOT_PARENT,
        handoff_index=index,
        mode=mode,  # type: ignore[arg-type]
        rows=tuple(ContinueRow(f"row {n} goes on", "", seed) for n in range(1, rows + 1)),
    )


def plan_of(njr: NormalizedJobRecord) -> SequencePlan:
    return SequencePlan.from_dict(dict(njr.stage_chain[0].extra)["sequence_metadata"])


def test_importing_and_inspecting_queue_nothing_and_the_tree_is_external(tmp_path):
    service, queue = make_service(tmp_path)
    clip = mp4(tmp_path / "elsewhere", "scene.mp4")
    plan = service.inspect_clip(str(clip), A14B)
    assert plan.route == "external" and plan.title == "scene" and plan.compatibility.compatible
    tree = service.create_from_clip_file(str(clip), "Scene", A14B)
    assert tree.root.origin == "external" and tree.root.job_id == "" and tree.root.kind == "clip"
    assert queue.calls == [] and service.store.load(tree.storyboard_id) == tree


def test_an_imported_root_admits_parallel_takes_from_a_middle_frame(tmp_path):
    service, queue = make_service(tmp_path)
    tree = service.create_from_clip_file(str(mp4(tmp_path / "e")), "Scene", A14B)
    result = service.submit(request(tree, mode="parallel", index=6, rows=3))
    assert queue.calls == [3]  # one submit_njrs call, three jobs
    plans = [plan_of(n) for n in queue.njrs]
    for plan in plans:
        link = plan.storyboard
        assert link is not None and link.lead_in is not None and link.lead_in.frame_count == 7
        assert link.handoff_index == 6 and link.parent_id == ROOT_PARENT
    assert len({p.segments[0].seed for p in plans}) == 3
    assert [t.handoff_index for t in result.tree.takes] == [6, 6, 6]


def test_an_imported_root_admits_a_sequential_chain_from_the_last_frame(tmp_path):
    service, queue = make_service(tmp_path)
    tree = service.create_from_clip_file(str(mp4(tmp_path / "e")), "Scene", A14B)
    result = service.submit(request(tree, mode="sequential", index=16, rows=2))
    assert queue.calls == [1] and len(plan_of(queue.njrs[0]).segments) == 2
    assert [t.chain_position for t in result.tree.takes] == [0, 1]
    preview = service.preview(
        request(service.store.load(tree.storyboard_id), mode="sequential", index=3)
    )
    assert preview.lead_in_frames == 4 and preview.fps == 16 and queue.calls == [1]


def test_admission_refuses_an_imported_handoff_frame_that_was_changed_or_moved(tmp_path):
    service, queue = make_service(tmp_path)
    tree = service.create_from_clip_file(str(mp4(tmp_path / "e")), "Scene", A14B)
    frames = [Path(frame.path) for frame in root_cut(tree.root).frames]
    frames[2].unlink()  # a lead-in frame that was moved away
    with pytest.raises(Exception, match="lead-in frame is missing"):
        service.submit(request(tree, mode="parallel", index=5, rows=1))
    frames[5].write_bytes(frames[5].read_bytes() + b"x")  # the handoff frame itself was changed
    with pytest.raises(Exception, match="changed"):
        service.submit(request(tree, mode="parallel", index=5, rows=1))
    assert queue.calls == []


@pytest.mark.parametrize("seed", ["12x", "-1", "2147483648", "1.5"])
def test_an_invalid_fixed_seed_is_refused_before_anything_is_saved_or_submitted(tmp_path, seed):
    service, queue = make_service(tmp_path)
    tree = service.create_from_clip_file(str(mp4(tmp_path / "e")), "Scene", A14B)
    with pytest.raises(StoryboardTreeError, match="Row 1"):
        service.submit(request(tree, mode="parallel", index=4, rows=1, seed=seed))
    with pytest.raises(StoryboardTreeError, match="Row 1"):
        service.preview(request(tree, mode="parallel", index=4, rows=1, seed=seed))
    assert queue.calls == [] and service.store.load(tree.storyboard_id).takes == ()


def test_random_and_fixed_seeds_map_to_admission_semantics(tmp_path):
    service, queue = make_service(tmp_path)
    tree = service.create_from_clip_file(str(mp4(tmp_path / "e")), "Scene", A14B)
    service.submit(request(tree, mode="parallel", index=4, rows=1, seed="random"))
    service.submit(
        request(
            service.store.load(tree.storyboard_id), mode="parallel", index=4, rows=1, seed="424242"
        )
    )
    drawn, fixed = (plan_of(n).segments[0].seed for n in queue.njrs)
    assert fixed == 424242 and 0 <= drawn < 2**31


def test_the_job_based_handoff_is_unchanged(tmp_path):
    repo, job_id, frames, _clip = known_clip(tmp_path)
    service, queue = make_service(tmp_path, repository=repo)
    tree = service.create_from_clip(job_id, "From a job")
    assert (
        tree.root.job_id == job_id
        and tree.root.origin == "job"
        and tree.root.to_dict().keys() == LEGACY_ROOT.keys()
    )
    assert queue.calls == [] and len(root_cut(tree.root).frames) == len(frames)
    by_file = service.create_from_clip_file(str(_clip), "From the file", A14B)
    assert by_file.root.job_id == job_id and by_file.root.origin == "job"


def test_an_incompatible_clip_is_refused_with_no_tree_and_no_files(tmp_path):
    service, queue = make_service(
        tmp_path, inspector=FakeInspector(probe(fps=30.0, rational="30/1"))
    )
    with pytest.raises(ClipImportError, match="invented or repeated frames"):
        service.create_from_clip_file(str(mp4(tmp_path / "e")), "Scene", A14B)
    assert nothing_published(tmp_path) and service.store.list_trees() == [] and queue.calls == []
