"""PR-VID-181 CPU-only launcher over the pinned upstream Wan2.2-Animate preprocessing components.

Run ONLY from the disposable qualification environment (never a StableNew/Comfy/A1111 env):

    <disposable>/Scripts/python.exe -m tools.qualification.vid181.preprocess_launcher \
        --upstream <wan22 checkout> --ckpt <ckpt dir> --video <driving.mp4> --refer <ref.png> \
        --out <dir> [--fps 30]

It reimplements only the *orchestration* of upstream ``process_pipepline.py``'s animation-mode,
``retarget_flag=False`` branch (that module imports FLUX/SAM2 at import time, which animation mode
does not need). Every semantic step calls pinned upstream source: ``Pose2d`` (detector + ViTPose-H),
``AAPoseMeta.from_humanapi_meta``, ``draw_aapose_by_meta_new``, ``resize_by_area``,
``get_frame_indices``, ``padding_resize``, ``get_face_bboxes``. No renderer is reimplemented.

Recorded deviations from ``preprocess_data.py``: (1) ``resize_by_area(..., divisor=16)`` (upstream's
own replacement-mode value) because its animation-mode default of 64 yields 448x832 for the
accepted 480x832 reference; (2) the launcher skips the unused ``pose2d(frames[:1])`` retarget
template call; (3) CUDA is disabled and ``Pose2d(device="cpu")`` is used explicitly.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

# CUDA must never be initialized by preprocessing (DIAG-GPU-130 block); set before any import.
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

from tools.qualification.vid181 import provenance as prov  # noqa: E402


def _git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--ckpt", required=True, help="dir containing det/ and pose2d/")
    parser.add_argument("--video", required=True)
    parser.add_argument("--refer", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args(argv)

    prov.assert_isolated_env(sys.prefix)
    upstream = Path(args.upstream)
    head = _git_head(upstream)
    if head != prov.UPSTREAM_SHA:
        raise RuntimeError(f"upstream checkout {head} != pinned {prov.UPSTREAM_SHA}")
    ckpt = Path(args.ckpt)
    det_path, pose_path = ckpt / prov.DET_MODEL, ckpt / prov.POSE_MODEL
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(upstream / "wan" / "modules" / "animate" / "preprocess"))
    import cv2
    import numpy as np
    import onnxruntime
    import torch
    from decord import VideoReader
    from human_visualization import draw_aapose_by_meta_new
    from pose2d import Pose2d
    from pose2d_utils import AAPoseMeta

    from utils import get_face_bboxes, get_frame_indices, padding_resize, resize_by_area

    try:
        import moviepy.editor as mpy
    except Exception:  # noqa: BLE001 - moviepy 2.x layout, same fallback as upstream
        import moviepy as mpy

    pose2d = Pose2d(
        checkpoint=str(pose_path), detector_checkpoint=str(det_path), device="cpu"
    )
    det_providers = pose2d.detector.session.get_providers()
    pose_providers = pose2d.model.session.get_providers()
    if det_providers != [prov.PROVIDER] or pose_providers != [prov.PROVIDER]:
        raise RuntimeError(f"non-CPU provider active: det={det_providers} pose={pose_providers}")
    if torch.cuda.is_initialized():
        raise RuntimeError("CUDA was initialized during CPU-only preprocessing")

    refer_img = cv2.imread(args.refer)[..., ::-1]
    refer_img = resize_by_area(
        refer_img, prov.WIDTH * prov.HEIGHT, divisor=prov.UPSTREAM_DIVISOR
    )
    refer_meta = pose2d([refer_img])[0]

    reader = VideoReader(args.video)
    frame_num = len(reader)
    video_fps = reader.get_avg_fps()
    duration = reader.get_frame_timestamp(-1)[-1]
    expected = int(duration * video_fps + 0.5)
    if abs((frame_num - expected) / frame_num) > 0.1:
        frame_num = expected
    fps = video_fps if args.fps == -1 else args.fps
    target_num = int(frame_num / video_fps * fps)
    idxs = get_frame_indices(frame_num, video_fps, target_num, fps)
    frames = reader.get_batch(idxs).asnumpy()

    metas = pose2d(frames)
    face_images = []
    for idx, meta in enumerate(metas):
        x1, x2, y1, y2 = get_face_bboxes(
            meta["keypoints_face"][:, :2], scale=1.3, image_shape=frames[0].shape[:2]
        )
        face_images.append(cv2.resize(frames[idx][y1:y2, x1:x2], (512, 512)))

    cond_images = []
    body_conf = []
    for meta in metas:
        aa = AAPoseMeta.from_humanapi_meta(meta)
        canvas = np.zeros_like(frames[0])
        drawn = draw_aapose_by_meta_new(canvas, aa)
        cond_images.append(padding_resize(drawn, refer_img.shape[0], refer_img.shape[1]))
        body_conf.append(float(np.asarray(meta["keypoints_body"])[:, 2].mean()))

    pose_path_out, face_path_out = out / "src_pose.mp4", out / "src_face.mp4"
    mpy.ImageSequenceClip(face_images, fps=fps).write_videofile(str(face_path_out), logger=None)
    mpy.ImageSequenceClip(cond_images, fps=fps).write_videofile(str(pose_path_out), logger=None)

    evidence = {
        "upstream_sha": head,
        "checkpoint_repo": prov.CHECKPOINT_REPO,
        "checkpoint_revision": prov.CHECKPOINT_REVISION,
        "python": platform.python_version(),
        "interpreter_prefix": sys.prefix,
        "versions": {
            "onnxruntime": onnxruntime.__version__,
            "torch": torch.__version__,
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
        "onnxruntime_available_providers": onnxruntime.get_available_providers(),
        "detector_providers": det_providers,
        "pose_providers": pose_providers,
        "torch_cuda_available": bool(torch.cuda.is_available()),
        "torch_cuda_initialized": bool(torch.cuda.is_initialized()),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "retarget_flag": False,
        "reference_detected_body_conf_mean": float(
            np.asarray(refer_meta["keypoints_body"])[:, 2].mean()
        ),
        "raw_video": {"path": str(args.video), "sha256": prov.sha256_of(Path(args.video))},
        "refer": {"path": str(args.refer), "sha256": prov.sha256_of(Path(args.refer))},
        "video_fps": video_fps,
        "video_frame_count": len(reader),
        "processed_fps": fps,
        "processed_frame_count": len(cond_images),
        "processed_indices_head": idxs[:5],
        "pose_output_size": [int(cond_images[0].shape[1]), int(cond_images[0].shape[0])],
        "per_frame_body_conf_mean_min": min(body_conf),
        "per_frame_body_conf_mean_mean": float(np.mean(body_conf)),
        "src_pose": {"path": str(pose_path_out), "sha256": prov.sha256_of(pose_path_out)},
        "src_face": {"path": str(face_path_out), "sha256": prov.sha256_of(face_path_out)},
        "deviations": [
            "resize_by_area divisor=16 (upstream replacement-mode value; default 64 -> 448x832)",
            "skipped unused pose2d(frames[:1]) retarget-template call",
            "thin launcher instead of preprocess_data.py (avoids module-level FLUX/SAM2 imports)",
        ],
    }
    (out / "preprocess_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
