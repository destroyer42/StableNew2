"""PR-VID-184 person-detector runner.

Runs ONLY inside the disposable CPU-only environment used by
``tools/qualification/vid181/preprocess_launcher.py`` (needs onnxruntime + opencv-python +
numpy, none of which are installed in the StableNew ``.venv``). It is invoked as a subprocess
from ``tracking.py`` (which runs in the StableNew ``.venv`` and only consumes the plain-JSON
output), the same split used by every prior PR-VID-1xx qualification package: heavy/third-party
detector inference stays outside the production interpreter.

This is new, self-contained detection code (YOLOv10 person-class boxes via the same
``yolov10m.onnx`` checkpoint PR-VID-181 already pinned), not a reuse of upstream Wan2.2's own
pose-extraction pipeline -- PR-VID-184 only needs person bounding boxes (continuity/ghost-actor
counting), not full pose estimation, so the much larger upstream animation-preprocessing pipeline
is not invoked here.

No network access. Reads a local video file and a local ONNX model file; writes a local JSON file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PERSON_CLASS_ID = 0
DEFAULT_SCORE_THRESHOLD = 0.35
INPUT_SIZE = 640


def _letterbox(frame: Any, size: int = INPUT_SIZE) -> tuple[Any, float, int, int]:
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    scale = min(size / w, size / h)
    new_w, new_h = round(w * scale), round(h * scale)
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


def _detect_frame(session, frame, *, score_threshold: float) -> list[list[float]]:
    import cv2
    import numpy as np

    canvas, scale, pad_x, pad_y = _letterbox(frame)
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    chw = np.transpose(rgb, (2, 0, 1))[None, ...]
    (output,) = session.run(None, {session.get_inputs()[0].name: chw})
    boxes: list[list[float]] = []
    for det in output[0]:
        x1, y1, x2, y2, score, class_id = det
        if int(round(float(class_id))) != PERSON_CLASS_ID or float(score) < score_threshold:
            continue
        ox1 = (float(x1) - pad_x) / scale
        oy1 = (float(y1) - pad_y) / scale
        ox2 = (float(x2) - pad_x) / scale
        oy2 = (float(y2) - pad_y) / scale
        boxes.append([ox1, oy1, ox2, oy2, float(score)])
    return boxes


def run(*, model_path: Path, video_path: Path, out_path: Path, score_threshold: float) -> dict:
    import cv2
    import onnxruntime as ort

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    active_providers = session.get_providers()
    if active_providers != ["CPUExecutionProvider"]:
        raise RuntimeError(f"refusing non-CPU-only active session providers: {active_providers}")

    capture = cv2.VideoCapture(str(video_path))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames: list[list[list[float]]] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(_detect_frame(session, frame, score_threshold=score_threshold))
    capture.release()

    payload = {
        "video_path": str(video_path),
        "frame_width": width,
        "frame_height": height,
        "fps": fps,
        "frame_count": len(frames),
        "score_threshold": score_threshold,
        "frames": frames,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    args = parser.parse_args(argv)
    run(
        model_path=args.model,
        video_path=args.video,
        out_path=args.out,
        score_threshold=args.score_threshold,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
