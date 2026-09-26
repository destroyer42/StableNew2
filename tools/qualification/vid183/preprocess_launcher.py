"""CPU-only PR-VID-183 pose preprocessing using pinned upstream Wan components.

Run this only from a disposable environment.  ``--case A`` reproduces the
accepted unretargeted pose projection; ``--case B`` calls upstream
``get_retarget_pose(..., None, None)`` directly with ``use_flux=False``.
Neither branch imports or executes FLUX/SAM2, and CUDA is disabled before any
runtime dependency imports.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

from tools.qualification.vid183 import provenance as prov  # noqa: E402


def _git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=("A", "B"))
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--ckpt", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--refer", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fps", type=int, default=8)
    args = parser.parse_args(argv)

    prov.assert_isolated_env(sys.prefix)
    upstream, ckpt, out = Path(args.upstream), Path(args.ckpt), Path(args.out)
    head = _git_head(upstream)
    if head != prov.UPSTREAM_SHA:
        raise RuntimeError(f"upstream checkout {head} != pinned {prov.UPSTREAM_SHA}")
    out.mkdir(parents=True, exist_ok=True)
    pose_path = ckpt / prov.POSE_MODEL
    det_path = ckpt / prov.DET_MODEL

    sys.path.insert(0, str(upstream / "wan" / "modules" / "animate" / "preprocess"))
    import cv2
    import numpy as np
    import onnxruntime
    import torch
    from decord import VideoReader
    from human_visualization import draw_aapose_by_meta_new
    from pose2d import Pose2d
    from pose2d_utils import AAPoseMeta
    from retarget_pose import get_retarget_pose

    from utils import get_face_bboxes, get_frame_indices, padding_resize, resize_by_area

    try:
        import moviepy.editor as mpy
    except Exception:  # noqa: BLE001 - supports both upstream moviepy layouts
        import moviepy as mpy

    pose2d = Pose2d(checkpoint=str(pose_path), detector_checkpoint=str(det_path), device="cpu")
    det_providers = pose2d.detector.session.get_providers()
    pose_providers = pose2d.model.session.get_providers()
    if det_providers != [prov.PROVIDER] or pose_providers != [prov.PROVIDER]:
        raise RuntimeError(f"non-CPU provider active: det={det_providers} pose={pose_providers}")
    if torch.cuda.is_initialized():
        raise RuntimeError("CUDA was initialized during CPU-only preprocessing")

    refer_img = cv2.imread(args.refer)[..., ::-1]
    refer_img = resize_by_area(refer_img, prov.WIDTH * prov.HEIGHT, divisor=prov.UPSTREAM_DIVISOR)
    refer_meta = pose2d([refer_img])[0]
    reader = VideoReader(args.video)
    frame_num, video_fps = len(reader), reader.get_avg_fps()
    target_num = int(frame_num / video_fps * args.fps)
    indices = get_frame_indices(frame_num, video_fps, target_num, args.fps)
    frames = reader.get_batch(indices).asnumpy()
    tpl_pose_meta0, tpl_pose_metas = pose2d(frames[:1])[0], pose2d(frames)
    # Upstream get_retarget_pose mutates its input metadata. Collect source detector evidence
    # first, so the A/B records describe the same unmodified driving observations.
    face_images, body_conf, lower_conf = [], [], []
    for frame, raw_meta in zip(frames, tpl_pose_metas, strict=True):
        x1, x2, y1, y2 = get_face_bboxes(
            raw_meta["keypoints_face"][:, :2], scale=1.3, image_shape=frames[0].shape[:2]
        )
        face_images.append(cv2.resize(frame[y1:y2, x1:x2], (512, 512)))
        body_conf.append(float(np.asarray(raw_meta["keypoints_body"])[:, 2].mean()))
        lower_conf.append(float(np.asarray(raw_meta["keypoints_body"])[[9, 10, 12, 13], 2].mean()))
    if args.case == "B":
        # This is exactly the pinned upstream no-FLUX basic branch; never reimplemented here.
        pose_metas = get_retarget_pose(tpl_pose_meta0, refer_meta, tpl_pose_metas, None, None)
    else:
        pose_metas = [AAPoseMeta.from_humanapi_meta(meta) for meta in tpl_pose_metas]

    cond_images = []
    for pose_meta in pose_metas:
        canvas = np.zeros_like(refer_img if args.case == "B" else frames[0])
        drawn = draw_aapose_by_meta_new(canvas, pose_meta)
        cond_images.append(
            drawn
            if args.case == "B"
            else padding_resize(drawn, refer_img.shape[0], refer_img.shape[1])
        )

    pose_out, face_out = out / "src_pose.mp4", out / "src_face.mp4"
    mpy.ImageSequenceClip(face_images, fps=args.fps).write_videofile(str(face_out), logger=None)
    mpy.ImageSequenceClip(cond_images, fps=args.fps).write_videofile(str(pose_out), logger=None)
    evidence = {
        "case": args.case,
        "upstream_sha": head,
        "checkpoint_repo": prov.CHECKPOINT_REPO,
        "checkpoint_revision": prov.CHECKPOINT_REVISION,
        "python": platform.python_version(),
        "interpreter_prefix": sys.prefix,
        "retarget_flag": args.case == "B",
        "use_flux": False,
        "retarget_implementation": "upstream retarget_pose.get_retarget_pose"
        if args.case == "B"
        else None,
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
        "reference_detected_body_conf_mean": float(
            np.asarray(refer_meta["keypoints_body"])[:, 2].mean()
        ),
        "raw_video": {"path": args.video, "sha256": prov.sha256_of(Path(args.video))},
        "refer": {"path": args.refer, "sha256": prov.sha256_of(Path(args.refer))},
        "video_fps": video_fps,
        "video_frame_count": len(reader),
        "processed_fps": args.fps,
        "processed_frame_count": len(cond_images),
        "processed_indices": indices,
        "pose_output_size": [int(cond_images[0].shape[1]), int(cond_images[0].shape[0])],
        "per_frame_body_conf_mean_min": min(body_conf),
        "per_frame_lower_body_conf": [round(c, 3) for c in lower_conf],
        "per_frame_body_conf_mean_mean": float(np.mean(body_conf)),
        "src_pose": {"path": str(pose_out), "sha256": prov.sha256_of(pose_out)},
        "src_face": {"path": str(face_out), "sha256": prov.sha256_of(face_out)},
        "deviations": [
            "resize_by_area divisor=16 (accepted upstream replacement-mode value)",
            "CPU-only Pose2d; CUDA disabled before runtime imports",
            "thin upstream orchestration only; FLUX/SAM2 omitted",
        ],
    }
    (out / "preprocess_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
