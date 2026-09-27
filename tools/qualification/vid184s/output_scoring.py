"""PR-VID-184S output scoring and cross-output comparison (qualification-only, no GPU).

Runs in the disposable CPU venv used by PR-VID-181/184 (needs cv2 + numpy + onnxruntime) with the
repository root on PYTHONPATH. It reuses the frozen PR-VID-184 detector/tracker and the reused
PR-VID-110 motion metrics; nothing here changes a threshold.

  score  : trim a saved Comfy .webm to the 39-frame evidence window, run the frozen metrics.
  compare: pairwise similarity between the trimmed clips of two arms.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

ENV = Path(r"C:\Users\rob\qual\vid184\env")
DETECTOR_MODEL = Path(r"C:\Users\rob\qual\vid181\ckpt\process_checkpoint\det\yolov10m.onnx")
DRIVING = ENV / "inputs" / "B_locomotion_driving_39f_candidate.mp4"
REFERENCE = ENV / "inputs" / "source_fullbody.png"
FFMPEG = (
    r"C:\Users\rob\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
)
EVIDENCE_FRAMES = 39


class ShortClipError(ValueError):
    """The saved output has fewer decodable frames than the frozen evidence window."""


def trim_to_mp4(webm: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(webm), "-frames:v", str(EVIDENCE_FRAMES),
         "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )  # fmt: skip
    # A source with fewer than EVIDENCE_FRAMES decodable frames still lets ffmpeg reach EOF and
    # emit a short (but otherwise valid) file; the downstream metrics would then silently score
    # a partial/truncated generation as if it were the full 39-frame evidence window.
    ffprobe = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
    r = subprocess.run(
        [ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    got = int(json.loads(r.stdout)["streams"][0]["nb_read_frames"])
    if got != EVIDENCE_FRAMES:
        raise ShortClipError(
            f"{webm} trimmed to {got} frames, not the frozen evidence window of {EVIDENCE_FRAMES}"
        )
    return out


def probe(webm: Path) -> dict[str, Any]:
    ffprobe = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
    r = subprocess.run(
        [ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height,r_frame_rate,nb_read_frames,duration", "-of", "json", str(webm)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(r.stdout)["streams"][0]


def _direction_sign(first: float | None, last: float | None) -> int:
    if first is None or last is None or first == last:
        return 0
    return 1 if last > first else -1


def driving_direction(work_root: Path) -> int:
    """Sign of the driving clip's own first->last primary-track centroid displacement, used to
    enforce the frozen contract's ``ROOT_TRANSLATION_DIRECTION_MUST_MATCH``."""
    from tools.qualification.vid184 import detect_runner, tracking

    payload = detect_runner.run(
        model_path=DETECTOR_MODEL, video_path=DRIVING, out_path=work_root / "driving_detect.json",
        score_threshold=detect_runner.DEFAULT_SCORE_THRESHOLD,
    )  # fmt: skip
    t = tracking.track(payload)
    return _direction_sign(t.first_centroid_x, t.last_centroid_x)


def score(webm: Path, work: Path) -> dict[str, Any]:
    from tools.qualification.vid110 import metrics as m
    from tools.qualification.vid184 import detect_runner, tracking
    from tools.qualification.vid184 import scoring_contract as sc

    sc.verify_contract_unchanged()
    trimmed = trim_to_mp4(webm, work / "trim39.mp4")
    payload = detect_runner.run(
        model_path=DETECTOR_MODEL, video_path=trimmed, out_path=work / "detect.json",
        score_threshold=detect_runner.DEFAULT_SCORE_THRESHOLD,
    )  # fmt: skip
    t = tracking.track(payload)
    curve = m.motion_curve(trimmed)
    corr = m.curve_correlation(curve, m.motion_curve(DRIVING))
    cm = m.clip_metrics(trimmed, source_image=REFERENCE)
    out_sign = _direction_sign(t.first_centroid_x, t.last_centroid_x)
    drive_sign = driving_direction(work.parent)
    direction_matches = out_sign != 0 and out_sign == drive_sign
    root_translation_pass = t.root_translation_fraction >= sc.ROOT_TRANSLATION_FRACTION_PASS and (
        not sc.ROOT_TRANSLATION_DIRECTION_MUST_MATCH or direction_matches
    )
    return {
        "source_webm": str(webm),
        "source_probe": probe(webm),
        "trimmed_frames": cm.frames,
        "primary_subject_continuity": t.primary_subject_continuity,
        "ghost_actor_persistence": t.ghost_actor_persistence,
        "root_translation_fraction": round(t.root_translation_fraction, 3),
        "root_translation_direction_matches_driving": direction_matches,
        "motion_curve_correlation": round(corr, 3),
        "identity_hist_mean": round(cm.identity_hist_mean or 0.0, 3),
        "identity_hist_min": round(cm.identity_hist_min or 0.0, 3),
        "camera_drift_px": round(cm.camera_drift_px, 3),
        "motion_area_fraction": round(cm.motion_area_fraction, 3),
        "passes": {
            "continuity": t.primary_subject_continuity >= sc.PRIMARY_SUBJECT_MIN_TRACK_COVERAGE,
            "ghost": t.ghost_actor_persistence <= sc.GHOST_ACTOR_MAX_PERSISTENT_FRAMES,
            "root_translation": root_translation_pass,
            "motion_curve": corr >= sc.MOTION_CURVE_CORRELATION_PASS,
        },
        "motion_curve": [round(x, 4) for x in curve],
        "centroid_x": _centroids(payload),
    }


def _centroids(payload: dict[str, Any]) -> list[float | None]:
    out: list[float | None] = []
    for boxes in payload["frames"]:
        if not boxes:
            out.append(None)
            continue
        b = max(boxes, key=lambda x: (x[2] - x[0]) * (x[3] - x[1]))
        out.append(round((b[0] + b[2]) / 2.0, 1))
    return out


def _read_trimmed_source_frames(webm: Path) -> list[Any]:
    """Decode the ORIGINAL saved Comfy output directly (no re-encode) and trim to the evidence
    window the same way ``legal_length.trim_to_evidence_window`` does -- keep the leading frames,
    drop the trailing ones. Used for pixel-level comparison so a claim of frame identity reflects
    the actual generated pixels, not an artifact of ``trim_to_mp4``'s lossy H.264 intermediate."""
    from tools.qualification.vid110 import metrics as m
    from tools.qualification.vid184 import legal_length as ll

    frames, _fps = m.read_frames(webm)
    return ll.trim_to_evidence_window(frames, EVIDENCE_FRAMES)


def compare(
    a_webm: Path, b_webm: Path, a_score: dict[str, Any], b_score: dict[str, Any]
) -> dict[str, Any]:
    import cv2
    import numpy as np

    from tools.qualification.vid110 import metrics as m

    fa = _read_trimmed_source_frames(a_webm)
    fb = _read_trimmed_source_frames(b_webm)
    n = min(len(fa), len(fb))
    psnr, hist = [], []
    for x, y in zip(fa[:n], fb[:n], strict=True):
        mse = float(np.mean((x.astype(np.float64) - y.astype(np.float64)) ** 2))
        psnr.append(99.0 if mse == 0 else float(10 * np.log10(255.0**2 / mse)))
        hx = cv2.calcHist(
            [cv2.cvtColor(x, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 16], [0, 180, 0, 256]
        )
        hy = cv2.calcHist(
            [cv2.cvtColor(y, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 16], [0, 180, 0, 256]
        )
        hist.append(
            float(
                cv2.compareHist(
                    cv2.normalize(hx, hx).flatten(),
                    cv2.normalize(hy, hy).flatten(),
                    cv2.HISTCMP_CORREL,
                )
            )
        )
    ca, cb = a_score["centroid_x"], b_score["centroid_x"]
    pairs = [(p, q) for p, q in zip(ca, cb, strict=True) if p is not None and q is not None]
    traj = (
        float(np.corrcoef([p for p, _ in pairs], [q for _, q in pairs])[0, 1])
        if len(pairs) > 2
        else None
    )
    traj_rms = float(np.sqrt(np.mean([(p - q) ** 2 for p, q in pairs]))) if pairs else None
    return {
        "frames_compared": n,
        "psnr_db_mean": round(float(np.mean(psnr)), 2),
        "psnr_db_min": round(float(np.min(psnr)), 2),
        "hsv_hist_correlation_mean": round(float(np.mean(hist)), 4),
        "root_trajectory_correlation": None if traj is None else round(traj, 4),
        "root_trajectory_rms_px": None if traj_rms is None else round(traj_rms, 1),
        "motion_curve_correlation_between_outputs": round(m.curve_correlation(a_score["motion_curve"], b_score["motion_curve"]), 4),
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--webm", type=Path, required=True)
    s.add_argument("--work", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument(
        "--a", type=Path, required=True, help="arm work dir containing trim39.mp4 + score.json"
    )
    c.add_argument("--b", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "score":
        result = score(args.webm, args.work)
        (args.work / "score.json").write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in ("motion_curve", "centroid_x")},
                indent=2,
            )
        )
    else:
        sa = json.loads((args.a / "score.json").read_text())
        sb = json.loads((args.b / "score.json").read_text())
        # Compare pixels decoded directly from the original saved outputs, not the lossy H.264
        # trim39.mp4 intermediate score() uses for the detector/metrics pipeline.
        print(
            json.dumps(compare(Path(sa["source_webm"]), Path(sb["source_webm"]), sa, sb), indent=2)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
