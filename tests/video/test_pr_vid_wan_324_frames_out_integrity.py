"""PR-VID-WAN-324 integrity: the frames-out record is only ever true about the clip it describes.

The frozen frame count is reconciled with the PNGs on disk (missing / extra / counter gaps and repeats); a missing or
unreadable frame fails before anything is encoded; the shared encoder can be told to fail rather than skip a frame,
and nothing else changes for the other exports; the acceptance wrapper fails a COMPLETED job whose frames, hashes,
clip or artifact identity do not hold; and 1.3.0 stays out of the catalog while the approved 1.2.0 stays offered.
Fake Comfy client and injected FFprobe, no GPU.
"""

from __future__ import annotations

import json
from builtins import range as builtin_range
from pathlib import Path
from typing import Any

import pytest

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline import video as pipeline_video
from src.pipeline.video import VideoCreator
from src.video import frames_out
from src.video.frames_out import encode_frames_out, reconcile_frame_count
from src.video.svd_errors import SVDExportError
from src.video.video_export import export_image_sequence_video
from src.video.workflow_catalog import (
    WAN22_FRAMES_VERSION,
    build_builtin_workflow_specs,
)
from src.video.workflow_contracts import (
    WORKFLOW_GOVERNANCE_APPROVED,
)
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry
from tests.video.test_pr_vid_wan_324_frames_out import (
    _fake_export,
    _frames_backend,
    _frames_request,
    _FramesComfy,
    _png,
    _sha,
)
from tests.video.test_wan22_experimental_workflow import WAN_ID
from tools.acceptance import vid324_frames_out_acceptance as acceptance


def _names(*numbers: int) -> list[str]:
    return [f"wan22_job_{n:05d}_.png" for n in numbers]


# ---------------------------------------------------------------------------
# reconciliation of the frozen count with the frames on disk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("numbers", "expected", "status", "gaps", "repeats", "difference"),
    [
        ((1, 2, 3, 4, 5), 5, "match", [], [], 0),
        ((1, 2, 3), 5, "missing", [], [], -2),
        ((1, 2, 4, 5, 6), 5, "missing", [3], [], 0),
        ((1, 2, 3, 4, 5, 6, 7), 5, "extra", [], [], 2),
        ((1, 2, 2, 3, 4), 5, "extra", [], [2], 0),
        ((1, 3, 3, 4, 5), 5, "missing_and_extra", [2], [3], 0),
        ((1, 2, 3), None, "unverified", [], [], None),
        ((7, 8, 9), 3, "match", [], [], 0),  # Comfy's counter need not start at 1
    ],
)
def test_the_frozen_count_is_reconciled_with_the_saved_frames(
    numbers, expected, status, gaps, repeats, difference
) -> None:
    result = reconcile_frame_count(_names(*numbers), expected)

    assert result["status"] == status
    assert result["sequence_gaps"] == gaps
    assert result["repeated_numbers"] == repeats
    assert result["difference"] == difference
    assert result["actual_frame_count"] == len(numbers)
    assert result["expected_frame_count"] == expected


def test_a_gap_listing_stays_bounded() -> None:
    result = reconcile_frame_count(_names(1, 1000), 2)

    assert result["status"] == "missing"
    assert result["sequence_gap_count"] == 998
    assert len(result["sequence_gaps"]) == 64


def test_sparse_remote_counters_do_not_expand_the_counter_span(monkeypatch) -> None:
    def bounded_range(*args):
        values = builtin_range(*args)
        assert len(values) <= 64, "remote frame counters must not drive an unbounded scan"
        return values

    monkeypatch.setattr(frames_out, "range", bounded_range, raising=False)
    result = reconcile_frame_count(_names(1, 10**12), 2)

    assert result["status"] == "missing"
    assert result["sequence_gap_count"] == 10**12 - 2
    assert result["sequence_gaps"] == list(builtin_range(2, 66))


# ---------------------------------------------------------------------------
# the encoder never records a frame the clip does not hold
# ---------------------------------------------------------------------------


def _recording_export(calls: list[dict[str, Any]]):
    def _export(**kwargs):
        calls.append(kwargs)
        return _fake_export(**kwargs)

    return _export


def test_a_missing_frame_fails_before_anything_is_encoded(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "src.video.frames_out.export_image_sequence_video", _recording_export(calls)
    )
    frames = [_png(tmp_path / name, 10) for name in _names(1, 2)]
    frames.append(tmp_path / _names(3)[0])  # listed by Comfy, never localized

    with pytest.raises(
        RuntimeError, match=r"1 of 3 saved frames cannot be encoded \(missing: wan22_job_00003_"
    ):
        encode_frames_out(frame_paths=frames, output_dir=tmp_path / "run", stem="clip", fps=24)
    assert calls == []
    assert not (tmp_path / "run" / "clip.mp4").exists()


@pytest.mark.parametrize("damage", ["garbage", "truncated"])
def test_an_unreadable_frame_fails_before_anything_is_encoded(
    tmp_path: Path, monkeypatch, damage: str
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "src.video.frames_out.export_image_sequence_video", _recording_export(calls)
    )
    frames = [_png(tmp_path / name, 40 * index) for index, name in enumerate(_names(1, 2, 3))]
    bad = frames[1]
    if damage == "garbage":
        bad.write_bytes(b"not a png")
    else:
        bad.write_bytes(bad.read_bytes()[:-30])

    with pytest.raises(RuntimeError, match=r"unreadable: wan22_job_00002_\.png"):
        encode_frames_out(frame_paths=frames, output_dir=tmp_path / "run", stem="clip", fps=24)
    assert calls == []


def test_extra_frames_are_encoded_and_reconciled_not_dropped(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "src.video.frames_out.export_image_sequence_video", _recording_export(calls)
    )
    frames = [_png(tmp_path / name, 20 * index) for index, name in enumerate(_names(1, 2, 3, 4))]

    record = encode_frames_out(
        frame_paths=frames, output_dir=tmp_path / "run", stem="clip", fps=24, expected_frame_count=3
    )

    assert len(calls[0]["image_paths"]) == 4 and calls[0]["require_all_frames"] is True
    assert record.frame_count == 4 and len(record.frame_sha256) == 4
    assert record.reconciliation["status"] == "extra"
    assert record.reconciliation["difference"] == 1


# ---------------------------------------------------------------------------
# the shared encoder's strict mode, and nothing else changes
# ---------------------------------------------------------------------------


def _creator_without_ffmpeg_probe() -> VideoCreator:
    creator = VideoCreator.__new__(VideoCreator)
    creator.ffmpeg_executable = Path("ffmpeg")
    creator.ffmpeg_available = True
    return creator


def _fake_ffmpeg(commands: list[list[str]]):
    class _Done:
        returncode = 0
        stderr = ""

    def _run(cmd, cancel=None):
        commands.append(list(cmd))
        Path(cmd[-1]).write_bytes(b"mp4")
        return _Done()

    return _run


def test_strict_staging_refuses_to_encode_with_a_skipped_frame(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(pipeline_video, "run_ffmpeg", _fake_ffmpeg(commands))
    images = [_png(tmp_path / "a_1.png", 1), tmp_path / "a_2.png", _png(tmp_path / "a_3.png", 3)]

    ok = _creator_without_ffmpeg_probe().create_video_from_images(
        images, tmp_path / "out" / "clip.mp4", require_all_frames=True
    )

    assert ok is False and commands == []


def test_default_staging_still_skips_a_missing_image(tmp_path: Path, monkeypatch) -> None:
    """Unchanged for every other export: a missing image is skipped and the rest are encoded."""

    commands: list[list[str]] = []
    monkeypatch.setattr(pipeline_video, "run_ffmpeg", _fake_ffmpeg(commands))
    images = [_png(tmp_path / "a_1.png", 1), tmp_path / "a_2.png", _png(tmp_path / "a_3.png", 3)]

    ok = _creator_without_ffmpeg_probe().create_video_from_images(
        images, tmp_path / "out" / "clip.mp4"
    )

    assert ok is True
    assert commands[0][commands[0].index("-frames:v") + 1] == "2"


class _OldCreator:
    """A creator written before the strict mode: it has no ``require_all_frames`` parameter."""

    ffmpeg_available = True

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, Any]] = []

    def create_video_from_images(
        self, image_paths, output_path, fps, codec, quality, *, settings=None, cancel=None
    ):
        self.calls.append({"image_paths": image_paths})
        return self.ok


def test_export_passes_the_strict_mode_only_when_asked(tmp_path: Path) -> None:
    creator = _OldCreator()
    export_image_sequence_video(
        image_paths=[tmp_path / "a.png"], output_path=tmp_path / "clip.mp4", fps=24, creator=creator
    )
    assert len(creator.calls) == 1

    failing = _OldCreator(ok=False)
    with pytest.raises(SVDExportError, match="failed to export image-sequence video"):
        export_image_sequence_video(
            image_paths=[tmp_path / "a.png"],
            output_path=tmp_path / "clip.mp4",
            fps=24,
            creator=failing,
        )


def test_a_strict_export_that_loses_a_frame_names_the_frame_count(tmp_path: Path) -> None:
    class _StrictCreator(_OldCreator):
        def create_video_from_images(
            self,
            image_paths,
            output_path,
            fps,
            codec,
            quality,
            *,
            settings=None,
            cancel=None,
            require_all_frames=False,
        ):
            self.calls.append({"require_all_frames": require_all_frames})
            return False

    creator = _StrictCreator()
    with pytest.raises(SVDExportError, match="all 2 frames"):
        export_image_sequence_video(
            image_paths=[tmp_path / "a.png", tmp_path / "b.png"],
            output_path=tmp_path / "clip.mp4",
            fps=24,
            creator=creator,
            require_all_frames=True,
        )
    assert creator.calls == [{"require_all_frames": True}]


# ---------------------------------------------------------------------------
# the backend
# ---------------------------------------------------------------------------


class _DamagedFramesComfy(_FramesComfy):
    def download_view(self, filename, destination, **kwargs):
        path = super().download_view(filename, destination, **kwargs)
        if filename.endswith("00002_.png"):
            Path(path).write_bytes(b"\x89PNG broken")
        return path


def test_the_backend_fails_a_job_whose_saved_frame_does_not_decode(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)

    with pytest.raises(RuntimeError, match="unreadable: wan22_job_00002_"):
        _frames_backend(_DamagedFramesComfy(tmp_path)).execute(None, _frames_request(tmp_path))
    assert not (tmp_path / "run" / f"{WAN_ID}_job-1.mp4").exists()


def test_the_backend_records_a_match_when_every_frozen_frame_was_saved(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )

    result = _frames_backend(_FramesComfy(tmp_path, frames=17)).execute(
        None, _frames_request(tmp_path)
    )

    frames_out = result.to_variant_payload()["frames_out"]
    assert frames_out["reconciliation"]["status"] == "match"
    assert (frames_out["frame_count"], frames_out["expected_frame_count"]) == (17, 17)


# ---------------------------------------------------------------------------
# the acceptance wrapper does not pass on COMPLETED alone
# ---------------------------------------------------------------------------


def _completed_job(tmp_path: Path, *, frames: int = 5, expected: int = 5) -> dict[str, Any]:
    """A harness evidence dict for one completed frames-out job, with real files behind it."""

    run = tmp_path / "run"
    paths = [
        _png(run / name, 30 * index) for index, name in enumerate(_names(*range(1, frames + 1)))
    ]
    digests = [_sha(path) for path in paths]
    job_id = "njr-324"
    clip = run / f"{WAN_ID}_{job_id}.mp4"
    clip.write_bytes(b"encoded clip")
    manifest_path = run / "manifests" / f"{clip.stem}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "workflow_id": WAN_ID,
        "workflow_version": WAN22_FRAMES_VERSION,
        "output_paths": [str(clip)],
        "frame_paths": [str(path) for path in paths],
        "manifest_paths": [str(manifest_path)],
        "artifact": {"primary_path": str(clip), "manifest_path": str(manifest_path)},
        "frames_out": {
            "video_path": str(clip),
            "fps": 24,
            "frame_count": frames,
            "expected_frame_count": expected,
            "first_frame_path": str(paths[0]),
            "last_frame_path": str(paths[-1]),
            "last_frame_sha256": digests[-1],
            "frame_paths": [str(path) for path in paths],
            "frame_sha256": digests,
            "reconciliation": reconcile_frame_count(paths, expected),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "admission": [
            {
                "label": "A",
                "job_id": job_id,
                "workflow_id": WAN_ID,
                "workflow_version": WAN22_FRAMES_VERSION,
                "frame_count": expected,
            }
        ],
        "jobs": [
            {
                "label": "A",
                "job_id": job_id,
                "status": "completed",
                "artifacts": [{"primary_path": str(clip), "manifest_path": str(manifest_path)}],
            }
        ],
    }


def _manifest(evidence: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = Path(evidence["jobs"][0]["artifacts"][0]["manifest_path"])
    return path, json.loads(path.read_text(encoding="utf-8"))


def _failed(result: dict[str, Any]) -> list[str]:
    return [item["check"] for item in result["checks"] if not item["ok"]]


def test_a_job_whose_artifacts_hold_passes(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert result["passed"], _failed(result)
    assert result["facts"]["encoded_frame_count"] == 5
    assert result["facts"]["last_frame_sha256"] == _sha(tmp_path / "run" / _names(5)[0])


def test_completed_without_artifacts_fails(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    evidence["jobs"][0]["artifacts"] = []

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert not result["passed"]
    assert "job artifact names a manifest" in _failed(result)


def test_a_frame_changed_after_hashing_fails(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    _png(tmp_path / "run" / _names(3)[0], 250)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert _failed(result) == ["every frame on disk matches its hash"]


def test_a_changed_last_frame_fails_the_exact_last_frame_check(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    _png(tmp_path / "run" / _names(5)[0], 251)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert set(_failed(result)) == {"every frame on disk matches its hash", "last frame is exact"}


@pytest.mark.parametrize(
    ("probe_result", "failed_check"),
    [
        ((4, 24.0), "encoded clip holds every frame"),
        ((5, 25.0), "encoded clip plays at the declared rate"),
    ],
)
def test_the_encoded_clip_is_checked_as_decoded(tmp_path: Path, probe_result, failed_check) -> None:
    evidence = _completed_job(tmp_path)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: probe_result)

    assert _failed(result) == [failed_check]


def test_a_probe_failure_fails_the_run(tmp_path: Path) -> None:
    def _broken(_clip):
        raise RuntimeError("FFprobe is not available to count the encoded frames")

    result = acceptance.verify_frames_out_evidence(_completed_job(tmp_path), probe=_broken)

    assert _failed(result) == ["encoded clip probed"]


def test_a_frame_count_that_does_not_reconcile_fails(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path, frames=4, expected=5)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (4, 24.0))

    assert _failed(result) == ["frozen count equals the frames saved"]


def test_a_manifest_frame_list_that_disagrees_fails(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    path, manifest = _manifest(evidence)
    manifest["frame_paths"] = manifest["frame_paths"][:-1]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert _failed(result) == ["manifest frame list is the encoded frame list"]


def test_a_primary_artifact_that_is_not_the_jobs_clip_fails(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    other = tmp_path / "run" / "someone_else.mp4"
    other.write_bytes(b"other")
    evidence["jobs"][0]["artifacts"][0]["primary_path"] = str(other)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert set(_failed(result)) == {
        "job primary is the encoded clip (or RIFE smoothing of its frames)",
        "job primary matches the manifest artifact",
    }


def test_a_smoothed_primary_made_from_the_frames_passes(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    path, manifest = _manifest(evidence)
    smoothed = tmp_path / "run" / f"{WAN_ID}_njr-324_smooth.mp4"
    smoothed.write_bytes(b"smooth")
    manifest["interpolation"] = {
        "video_path": str(smoothed),
        "source_video_path": str(tmp_path / "run"),
    }
    manifest["output_paths"].insert(0, str(smoothed))
    manifest["artifact"]["primary_path"] = str(smoothed)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    evidence["jobs"][0]["artifacts"][0]["primary_path"] = str(smoothed)

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert result["passed"], _failed(result)


def test_a_job_on_another_version_fails(tmp_path: Path) -> None:
    evidence = _completed_job(tmp_path)
    evidence["admission"][0]["workflow_version"] = "1.2.0"

    result = acceptance.verify_frames_out_evidence(evidence, probe=lambda _clip: (5, 24.0))

    assert set(_failed(result)) == {
        "admitted on the frames-out version",
        "manifest workflow matches admission",
    }


def test_the_wrapper_verifies_after_a_completed_harness_run(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    monkeypatch.setattr(acceptance, "REPORTS_DIR", str(reports))
    monkeypatch.setattr(acceptance, "_register_frames_out_version", lambda: None)
    passthrough: list[list[str]] = []
    monkeypatch.setattr(acceptance.harness, "main", lambda args: passthrough.append(args) or 0)

    assert (
        acceptance.main(["source.png"]) == 1
    )  # COMPLETED by the harness, but no evidence to verify
    verdict = json.loads((reports / acceptance.VERIFICATION_FILE).read_text(encoding="utf-8"))
    assert verdict["passed"] is False
    assert passthrough[0][passthrough[0].index("--workflow-version") + 1] == WAN22_FRAMES_VERSION

    (reports / "acceptance.json").write_text(json.dumps(_completed_job(tmp_path)), encoding="utf-8")
    assert acceptance.verify_reports(reports, probe=lambda _clip: (5, 24.0)) == 0


def test_a_dry_run_or_failed_harness_is_not_verified(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(acceptance, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(acceptance, "_register_frames_out_version", lambda: None)
    monkeypatch.setattr(acceptance, "verify_reports", lambda *_a, **_k: pytest.fail("verified"))

    monkeypatch.setattr(acceptance.harness, "main", lambda _args: 0)
    assert acceptance.main(["source.png", "--dry"]) == 0
    monkeypatch.setattr(acceptance.harness, "main", lambda _args: 1)
    assert acceptance.main(["source.png"]) == 1


# ---------------------------------------------------------------------------
# catalog policy: approved 1.3.0 offered, approved 1.2.0 still resolvable for replay
# ---------------------------------------------------------------------------


def _offered(registry: WorkflowRegistry) -> dict[str, dict[str, Any]]:
    """What the video picker offers, through the controller's own path."""

    controller = VideoWorkflowController(
        app_controller=None, workflow_registry=DefaultWorkflowRegistryPort(registry)
    )
    return {record["workflow_id"]: record for record in controller.list_workflow_specs()}


def test_approved_1_3_0_is_the_offered_version_and_approved_1_2_0_still_resolves() -> None:
    assert (WAN_ID, WAN22_FRAMES_VERSION) in {
        (spec.workflow_id, spec.workflow_version) for spec in build_builtin_workflow_specs()
    }
    registry = build_default_workflow_registry()
    assert registry.list_versions(WAN_ID)[-2:] == ["1.2.0", WAN22_FRAMES_VERSION]

    offered = _offered(registry)[WAN_ID]
    assert (offered["workflow_version"], offered["governance_state"]) == (
        WAN22_FRAMES_VERSION,
        WORKFLOW_GOVERNANCE_APPROVED,
    )
    # both run without any opt-in; the older one keeps Comfy's own SaveVideo output for replay
    frames = registry.get(WAN_ID, WAN22_FRAMES_VERSION)
    assert frames.backend_defaults["prompt_template"]["11"]["class_type"] == "SaveImage"
    approved = registry.get(WAN_ID, "1.2.0")
    assert approved.backend_defaults["prompt_template"]["12"]["class_type"] == "SaveVideo"
