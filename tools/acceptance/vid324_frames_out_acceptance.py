"""PR-VID-WAN-324 real acceptance: one Wan2.2 TI2V-5B job on the frames-out graph (1.3.0).

The frames-out spec is not in the built-in catalog until this run proves it, so this wrapper adds it to the
registry for this process only and then drives the PR-VID-190 acceptance harness unchanged (isolated scratch
workspace and queue, production chain ``VideoWorkflowController -> NJR -> JobService -> PipelineRunner.run_njr ->
ComfyWorkflowVideoBackend``, the operator's Comfy settings read-only, no process stopped or adopted).

A COMPLETED job is not enough. ``verify_frames_out_evidence`` then re-reads what the job left: the manifest's
frame list and its reconciliation with the frozen count, every PNG's SHA-256, the exact last frame, the encoded
MP4's decoded frame count and frame rate (FFprobe), and that the job's artifact, manifest and clip are one
identity. Any failed check fails the run; the checks land in ``<reports>/frames_out_verification.json``.

    python -m tools.acceptance.vid324_frames_out_acceptance <source.png> [--dry]
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.acceptance import vid190_queue_recycling_acceptance as harness

REPORTS_DIR = "reports/vid324"
JOB_LABEL = "A"
WORKFLOW_ID = "wan22_ti2v_5b_i2v_v1"
FRAMES_VERSION = "1.3.0"
VERIFICATION_FILE = "frames_out_verification.json"

# (decoded frame count, frame rate) of an encoded clip
VideoProbe = Callable[[Path], tuple[int, float]]


def _register_frames_out_version() -> None:
    from src.video import workflow_registry
    from src.video.workflow_catalog import _build_wan22_ti2v_5b_i2v_v1_3

    builtin = workflow_registry.build_builtin_workflow_specs

    def with_frames_out() -> tuple:
        return (*builtin(), _build_wan22_ti2v_5b_i2v_v1_3())

    workflow_registry.build_builtin_workflow_specs = with_frames_out


def probe_encoded_video(path: Path) -> tuple[int, float]:
    """Decode the clip with FFprobe and return its actual frame count and frame rate."""

    from src.video.container_metadata import resolve_ffprobe_executable

    ffprobe = resolve_ffprobe_executable()
    if ffprobe is None:
        raise RuntimeError("FFprobe is not available to count the encoded frames")
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {completed.stderr.strip()[:300]}")
    stream = (json.loads(completed.stdout or "{}").get("streams") or [{}])[0]
    rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    fps = 0.0 if rate.endswith("/0") else float(Fraction(rate))
    return int(stream.get("nb_read_frames") or 0), fps


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_path(left: Any, right: Any) -> bool:
    if not left or not right:
        return False
    return Path(str(left)).resolve() == Path(str(right)).resolve()


def verify_frames_out_evidence(
    evidence: Mapping[str, Any],
    *,
    label: str = JOB_LABEL,
    probe: VideoProbe = probe_encoded_video,
) -> dict[str, Any]:
    """Check the completed frames-out job against its own artifacts; ``passed`` only when every check holds."""

    checks: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}

    def check(name: str, ok: bool, detail: Any = None) -> bool:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def verdict() -> dict[str, Any]:
        return {
            "label": label,
            "passed": bool(checks) and all(item["ok"] for item in checks),
            "checks": checks,
            "facts": facts,
        }

    record = next((job for job in evidence.get("jobs") or [] if job.get("label") == label), None)
    admission = next(
        (job for job in evidence.get("admission") or [] if job.get("label") == label), None
    )
    if record is None or admission is None:
        check(
            "job admitted and ran",
            False,
            {"admitted": admission is not None, "ran": record is not None},
        )
        return verdict()
    check("job completed", record.get("status") == "completed", record.get("status"))
    check(
        "admitted on the frames-out version",
        (admission.get("workflow_id"), admission.get("workflow_version"))
        == (WORKFLOW_ID, FRAMES_VERSION),
        [admission.get("workflow_id"), admission.get("workflow_version")],
    )
    artifacts = record.get("artifacts") or []
    artifact = artifacts[0] if artifacts else {}
    manifest_path = Path(str(artifact.get("manifest_path") or ""))
    if not check(
        "job artifact names a manifest",
        bool(artifact.get("manifest_path")) and manifest_path.is_file(),
        artifact.get("manifest_path"),
    ):
        return verdict()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames_out = manifest.get("frames_out")
    if not check("manifest has a frames_out block", isinstance(frames_out, Mapping)):
        return verdict()

    frame_paths = [str(path) for path in frames_out.get("frame_paths") or []]
    digests = [str(digest) for digest in frames_out.get("frame_sha256") or []]
    clip = Path(str(frames_out.get("video_path") or ""))
    primary = artifact.get("primary_path")
    interpolation = manifest.get("interpolation") or {}
    manifest_artifact = manifest.get("artifact") or {}

    # --- artifact identity: the job's artifact, its manifest and the encoded clip are one thing ---
    job_id = str(record.get("job_id") or "")
    check(
        "manifest is the job's own",
        any(_same_path(path, manifest_path) for path in manifest.get("manifest_paths") or [])
        and _same_path(manifest_artifact.get("manifest_path"), manifest_path),
    )
    check(
        "manifest workflow matches admission",
        (manifest.get("workflow_id"), manifest.get("workflow_version"))
        == (admission.get("workflow_id"), admission.get("workflow_version")),
    )
    check("encoded clip is named for the job", bool(job_id) and job_id in clip.stem, clip.name)
    check(
        "encoded clip is a recorded output",
        any(_same_path(path, clip) for path in manifest.get("output_paths") or []),
    )
    smoothed_from_frames = (
        bool(frame_paths)
        and _same_path(primary, interpolation.get("video_path"))
        and _same_path(interpolation.get("source_video_path"), Path(frame_paths[0]).parent)
    )
    check(
        "job primary is the encoded clip (or RIFE smoothing of its frames)",
        _same_path(primary, clip) or smoothed_from_frames,
        primary,
    )
    check(
        "job primary matches the manifest artifact",
        _same_path(primary, manifest_artifact.get("primary_path")),
    )

    # --- the frame list, reconciled with the count frozen at admission ---
    expected = admission.get("frame_count")
    reconciliation = frames_out.get("reconciliation") or {}
    manifest_frames = manifest.get("frame_paths") or []
    facts.update(
        expected_frame_count=expected,
        frame_count=frames_out.get("frame_count"),
        reconciliation=reconciliation,
    )
    check(
        "manifest frame list is the encoded frame list",
        bool(frame_paths)
        and len(frame_paths) == len(manifest_frames)
        and all(_same_path(a, b) for a, b in zip(frame_paths, manifest_frames, strict=False)),
    )
    check(
        "one hash per listed frame",
        len(digests) == len(frame_paths) == frames_out.get("frame_count"),
        [len(digests), len(frame_paths), frames_out.get("frame_count")],
    )
    check(
        "frozen count equals the frames saved",
        isinstance(expected, int)
        and frames_out.get("expected_frame_count") == expected
        and frames_out.get("frame_count") == expected
        and reconciliation.get("status") == "match",
        {"admitted": expected, "status": reconciliation.get("status")},
    )

    # --- every PNG, and the exact last frame ---
    mismatched = [
        Path(text).name
        for text, digest in zip(frame_paths, digests, strict=False)  # lengths are checked above
        if not Path(text).is_file() or _sha256(Path(text)) != digest
    ]
    check(
        "every frame on disk matches its hash",
        bool(frame_paths) and not mismatched,
        mismatched[:10],
    )
    last_ok = False
    if frame_paths and digests:
        last = Path(frame_paths[-1])
        last_ok = (
            _same_path(frames_out.get("last_frame_path"), last)
            and frames_out.get("last_frame_sha256") == digests[-1]
            and last.is_file()
            and _sha256(last) == digests[-1]
        )
        facts["last_frame_sha256"] = frames_out.get("last_frame_sha256")
    check("last frame is exact", last_ok)

    # --- the encoded clip as decoded, not as recorded ---
    if check("encoded clip exists", clip.is_file(), str(clip)):
        facts["encoded_clip_sha256"] = _sha256(clip)
        try:
            decoded, fps = probe(clip)
        except Exception as exc:  # noqa: BLE001 - a probe failure fails the check, not the tool
            check("encoded clip probed", False, f"{type(exc).__name__}: {exc}"[:300])
        else:
            facts.update(encoded_frame_count=decoded, encoded_fps=fps)
            check(
                "encoded clip holds every frame",
                decoded == frames_out.get("frame_count") == len(digests),
                [decoded, frames_out.get("frame_count")],
            )
            check(
                "encoded clip plays at the declared rate",
                abs(fps - float(frames_out.get("fps") or 0)) < 0.01,
                [fps, frames_out.get("fps")],
            )
    return verdict()


def verify_reports(reports_dir: Path, *, probe: VideoProbe = probe_encoded_video) -> int:
    """Verify the harness evidence in ``reports_dir``, write the verdict beside it, return the exit code."""

    evidence_path = reports_dir / "acceptance.json"
    if evidence_path.is_file():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        result = verify_frames_out_evidence(evidence, probe=probe)
    else:
        result = {
            "label": JOB_LABEL,
            "passed": False,
            "checks": [
                {"check": "harness evidence exists", "ok": False, "detail": str(evidence_path)}
            ],
            "facts": {},
        }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / VERIFICATION_FILE).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    source = next((arg for arg in args if not arg.startswith("-")), None)
    if source is None:
        raise SystemExit(
            "usage: python -m tools.acceptance.vid324_frames_out_acceptance <source.png> [--dry]"
        )
    _register_frames_out_version()
    passthrough = [
        source,
        "--suite",
        "ti2v",
        "--only",
        JOB_LABEL,
        "--workflow-version",
        FRAMES_VERSION,
        "--reports-dir",
        REPORTS_DIR,
    ]
    dry = "--dry" in args
    if dry:
        passthrough.append("--dry")
    code = harness.main(passthrough)
    if dry or code != 0:
        return code
    return verify_reports(Path(REPORTS_DIR))


if __name__ == "__main__":
    sys.exit(main())
